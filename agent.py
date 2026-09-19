#!/usr/bin/env python3
"""
وكيل رصد أخبار الفيزياء البحثية — آفاق فيزيائية (نبض الأبحاث)
=================================================

يبحث أسبوعيًا في مصادر الفيزياء الموثوقة (APS, Nature, Physics World,
EurekAlert, المختبرات والجامعات الكبرى...) عن آخر 7 أيام من الأخبار
البحثية ضمن 12 مجالًا فيزيائيًا محددًا في instructions.md.

آلية البحث: بما أن ميزة Google Search grounding المدمجة في Gemini API
غير متاحة على الخطة المجانية (Free tier) إطلاقًا، يعتمد الوكيل بدلاً من
ذلك على بحث حقيقي وحيّ عبر **Tavily Search API** (مجانية بالكامل — 1000
طلب بحث شهريًا بدون بطاقة ائتمان) لكل مجال من المجالات الاثني عشر، ثم
يُمرَّر مجمع النتائج الحقيقية (بعناوينها وروابطها وتواريخها كما وردت من
محرك البحث) إلى Gemini الذي يقوم فقط بالفرز والتحقق والتنسيق النهائي وفق
معايير `instructions.md` الصارمة — بدون اختلاق أي معلومة غير موجودة في
نتائج Tavily الفعلية.

يحفظ الوكيل النشرة الناتجة بصيغة Markdown في reports/ وينشرها كمسودة
(draft) على ووردبريس للمراجعة قبل النشر الفعلي.

هذا السكربت مصمم للتشغيل داخل GitHub Actions (انظر
.github/workflows/weekly-radar.yml) لكنه يعمل محليًا كذلك.

المتغيرات البيئية المطلوبة:
    GEMINI_API_KEY      مفتاح Google Gemini API (من aistudio.google.com/apikey)
    TAVILY_API_KEY      مفتاح Tavily Search API المجاني (من tavily.com، بدون بطاقة)
    WP_URL              رابط الموقع، مثل: https://phy-lab.com
    WP_USER             اسم مستخدم ووردبريس (له صلاحية نشر)
    WP_APP_PASSWORD     كلمة مرور تطبيق ووردبريس (Application Password)

متغيرات اختيارية:
    GEMINI_MODEL        معرّف النموذج (افتراضي أدناه — تحقق من
                         https://ai.google.dev/gemini-api/docs/models
                         لأحدث معرّف عند الحاجة)
    WP_CATEGORY_NAME    اسم تصنيف ووردبريس المستهدف (افتراضي: "نبض الأبحاث")
    PUBLISH_STATUS      "draft" (افتراضي) أو "publish"
    LOOKBACK_DAYS       عدد الأيام للبحث (افتراضي: 7)
"""

from __future__ import annotations

import datetime as dt
import os
import pathlib
import re
import sys
import time

import markdown as md
import requests
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

REPO_ROOT = pathlib.Path(__file__).resolve().parent
INSTRUCTIONS_PATH = REPO_ROOT / "instructions.md"
REPORTS_DIR = REPO_ROOT / "reports"

DEFAULT_MODEL = "gemini-3.6-flash"
DEFAULT_CATEGORY_NAME = "نبض الأبحاث"
DEFAULT_LOOKBACK_DAYS = 7
MAX_OUTPUT_TOKENS = 16000
# سقف أمان لعدد جولات المتابعة عند توقف الرد بسبب تجاوز الحد الأقصى للمخرجات
MAX_CONTINUATION_ROUNDS = 12

CONTINUE_PROMPT = (
    "تابع من حيث توقفت تمامًا، دون إعادة كتابة أي جزء سبق أن أنتجته، "
    "حتى تكمل التقرير النهائي الكامل."
)

# مهلات إعادة المحاولة (بالثواني) عند ضغط مؤقت على خادم Gemini (503
# UNAVAILABLE) — إضافية فوق إعادة المحاولة المدمجة في SDK نفسه، لأن
# التشغيل التلقائي عبر GitHub Actions لا يوجد فيه إنسان لإعادة التشغيل
# يدويًا.
GEMINI_SERVER_RETRY_DELAYS = [20, 45, 90]

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
# نتائج tier-1 (المصادر الأساسية الأكثر موثوقية من القسم 3 في instructions.md)
TIER1_SEARCH_DOMAINS = [
    "aps.org",
    "physics.aps.org",
    "nature.com",
    "physicsworld.com",
    "physicstoday.org",
    "science.org",
    "eurekalert.org",
]
MAX_RESULTS_PER_DOMAIN = 12  # أقصى عدد نتائج فريدة تُمرَّر لكل مجال فيزيائي في السياق

# المجالات الاثنا عشر (مطابقة تمامًا للقسم 2 في instructions.md) مع كلمات مفتاحية
# إنجليزية تُستخدم لبناء استعلامات Tavily.
DOMAINS: list[dict] = [
    {
        "key": "renewable_energy",
        "name_ar": "الطاقة المتجددة ومواد الطاقة",
        "name_en": "Renewable Energy & Energy Materials",
        "keywords": [
            "photovoltaics", "solar cells", "perovskite solar cells",
            "energy storage", "batteries", "supercapacitors", "thermoelectrics",
            "hydrogen fuel cells",
        ],
    },
    {
        "key": "semiconductors",
        "name_ar": "فيزياء أشباه الموصلات والإلكترونيات",
        "name_en": "Semiconductor Physics & Electronics",
        "keywords": [
            "semiconductor physics", "2D semiconductors", "transistors",
            "nanoelectronics", "optoelectronics", "photodetectors",
            "quantum dots", "spintronics", "semiconductor lasers",
        ],
    },
    {
        "key": "plasma_fusion",
        "name_ar": "فيزياء البلازما والاندماج",
        "name_en": "Plasma Physics & Fusion",
        "keywords": [
            "plasma physics", "nuclear fusion", "fusion energy",
            "magnetic confinement", "inertial confinement",
            "laser-plasma interaction", "plasma accelerators",
        ],
    },
    {
        "key": "polymer_soft_matter",
        "name_ar": "فيزياء البوليمرات والمواد اللينة",
        "name_en": "Polymer Physics & Soft Matter",
        "keywords": [
            "polymer physics", "conductive polymers", "polymer nanocomposites",
            "soft matter", "organic semiconductors", "polymer electronics",
            "sustainable polymers",
        ],
    },
    {
        "key": "advanced_materials",
        "name_ar": "فيزياء المواد المتقدمة",
        "name_en": "Advanced Materials Physics",
        "keywords": [
            "quantum materials", "metamaterials", "superconductors",
            "topological materials", "MXenes", "graphene", "2D materials",
            "thin films",
        ],
    },
    {
        "key": "quantum_tech",
        "name_ar": "فيزياء الكم وتقنيات الكم",
        "name_en": "Quantum Physics & Quantum Technologies",
        "keywords": [
            "quantum computing", "quantum communication", "quantum sensing",
            "quantum materials", "quantum information", "quantum optics",
        ],
    },
    {
        "key": "nanophysics",
        "name_ar": "النانوفيزياء",
        "name_en": "Nanophysics & Nanotechnology",
        "keywords": [
            "nanophysics", "nanomaterials", "nanostructures", "nanodevices",
            "2D materials", "quantum dots",
        ],
    },
    {
        "key": "photonics_optics",
        "name_ar": "الفوتونيات والبصريات",
        "name_en": "Photonics & Optical Physics",
        "keywords": [
            "photonics", "nonlinear optics", "optical materials",
            "integrated photonics", "lasers", "optical sensors", "plasmonics",
        ],
    },
    {
        "key": "condensed_matter",
        "name_ar": "فيزياء المادة المكثفة",
        "name_en": "Condensed Matter Physics",
        "keywords": [
            "condensed matter physics", "solid state physics",
            "magnetic materials", "superconductivity",
            "strongly correlated materials", "phase transitions",
        ],
    },
    {
        "key": "nuclear_particle",
        "name_ar": "الفيزياء النووية وفيزياء الجسيمات",
        "name_en": "Nuclear & Particle Physics",
        "keywords": [
            "nuclear physics", "particle physics", "high energy physics",
            "CERN", "neutrinos", "fundamental particles",
        ],
    },
    {
        "key": "astrophysics_cosmology",
        "name_ar": "الفيزياء الفلكية والكونيات",
        "name_en": "Astrophysics & Cosmology",
        "keywords": [
            "astrophysics", "cosmology", "black holes", "gravitational waves",
            "dark matter", "dark energy", "exoplanets",
        ],
    },
    {
        "key": "ai_computational_physics",
        "name_ar": "الذكاء الاصطناعي والحوسبة في الفيزياء",
        "name_en": "AI, Computational Physics & Scientific Machine Learning",
        "keywords": [
            "machine learning for physics", "scientific machine learning",
            "computational physics", "physics-informed neural networks",
            "AI for materials discovery", "AI for scientific discovery",
        ],
    },
]


def load_instructions() -> str:
    if not INSTRUCTIONS_PATH.exists():
        sys.exit(f"لم يتم العثور على ملف التعليمات: {INSTRUCTIONS_PATH}")
    return INSTRUCTIONS_PATH.read_text(encoding="utf-8")


def _tavily_time_range(lookback_days: int) -> str:
    if lookback_days <= 1:
        return "day"
    if lookback_days <= 7:
        return "week"
    if lookback_days <= 31:
        return "month"
    return "year"


def tavily_search(
    api_key: str,
    query: str,
    *,
    include_domains: list[str] | None = None,
    max_results: int = 8,
    time_range: str = "week",
) -> list[dict]:
    """يستدعي Tavily Search API (مجاني، بدون بطاقة) ويعيد نتائج بحث حقيقية
    حديثة. لا يُختلق أي شيء هنا — النتائج تأتي كما هي من محرك البحث."""

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload: dict = {
        "query": query,
        "search_depth": "basic",
        "topic": "news",
        "time_range": time_range,
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
    }
    if include_domains:
        payload["include_domains"] = include_domains

    try:
        resp = requests.post(TAVILY_SEARCH_URL, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json().get("results", []) or []
    except requests.RequestException as exc:
        print(f"تحذير: فشل استعلام Tavily لـ '{query}': {exc}", file=sys.stderr)
        return []


def gather_search_pool(tavily_api_key: str, lookback_days: int) -> dict[str, list[dict]]:
    """ينفّذ بحثًا حقيقيًا منفصلاً لكل مجال من المجالات الاثني عشر عبر
    Tavily: استعلام أول مقيَّد بمصادر tier-1 الموثوقة (القسم 3 في
    instructions.md)، واستعلام ثانٍ عام يغطي المختبرات والجامعات ومصادر
    أخرى. يعيد قاموسًا {مفتاح_المجال: [نتائج حقيقية فريدة]}."""

    time_range = _tavily_time_range(lookback_days)
    pool_by_domain: dict[str, list[dict]] = {}

    for domain in DOMAINS:
        seen_urls: set[str] = set()
        collected: list[dict] = []
        keyword_str = ", ".join(domain["keywords"][:6])
        base_query = (
            f"latest {domain['name_en']} research news this week: {keyword_str}"
        )

        for include_domains, max_results in (
            (TIER1_SEARCH_DOMAINS, 8),
            (None, 6),
        ):
            results = tavily_search(
                tavily_api_key,
                base_query,
                include_domains=include_domains,
                max_results=max_results,
                time_range=time_range,
            )
            for r in results:
                url = (r.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                collected.append(
                    {
                        "title": (r.get("title") or "").strip(),
                        "url": url,
                        "published_date": (r.get("published_date") or "").strip(),
                        "content": (r.get("content") or "").strip()[:600],
                    }
                )
                if len(collected) >= MAX_RESULTS_PER_DOMAIN:
                    break
            if len(collected) >= MAX_RESULTS_PER_DOMAIN:
                break

        pool_by_domain[domain["key"]] = collected
        print(
            f"  [Tavily] {domain['name_en']}: {len(collected)} نتيجة فريدة",
            file=sys.stderr,
        )

    return pool_by_domain


def format_search_pool(pool_by_domain: dict[str, list[dict]]) -> str:
    """يبني نص السياق الذي يُمرَّر لـ Gemini: نتائج Tavily الحقيقية فقط،
    مجمّعة حسب المجال. هذا هو المصدر الوحيد المسموح باستخلاص الأخبار منه."""

    lines: list[str] = []
    for domain in DOMAINS:
        items = pool_by_domain.get(domain["key"], [])
        lines.append(f"## المجال: {domain['name_ar']} / {domain['name_en']}")
        if not items:
            lines.append("(لا توجد أي نتائج بحث حقيقية لهذا المجال في هذا التشغيل.)")
            lines.append("")
            continue
        for i, item in enumerate(items, 1):
            lines.append(
                f"{i}. العنوان (كما ورد حرفيًا): {item['title']}\n"
                f"   الرابط: {item['url']}\n"
                f"   تاريخ النشر كما ورد من محرك البحث: "
                f"{item['published_date'] or 'غير متوفر — تحقق من المحتوى أدناه أو استبعد الخبر إن تعذّر التحقق'}\n"
                f"   مقتطف من المحتوى: {item['content']}\n"
            )
        lines.append("")
    return "\n".join(lines)


def build_user_prompt(
    start: dt.date, end: dt.date, lookback_days: int, search_pool_text: str
) -> str:
    return (
        f"التاريخ الحالي هو: {end.isoformat()}.\n"
        f"النطاق الزمني المطلوب لهذا التشغيل الأسبوعي هو آخر {lookback_days} أيام: "
        f"من {start.isoformat()} إلى {end.isoformat()} (التزم بهذا النطاق حرفيًا، "
        "ولا تعتمد على تقديرك الخاص لليوم أو الأسبوع).\n\n"
        "تنبيه مهم حول آلية البحث في هذا التشغيل: لا تملك أداة بحث حي مباشر على "
        "الويب في هذه الجلسة. بدلاً من ذلك، تم تنفيذ بحث حقيقي فعلي مسبقًا عبر "
        "Tavily Search API لكل مجال من المجالات الاثني عشر (استعلام مقيّد "
        "بالمصادر الأساسية الموثوقة + استعلام عام يغطي المختبرات والجامعات "
        "ومصادر أخرى)، والنتائج الحقيقية كما وردت حرفيًا من محرك البحث مذكورة "
        "أدناه بين <SEARCH_RESULTS> و</SEARCH_RESULTS>.\n\n"
        "هذه القائمة هي **المصدر الوحيد المسموح به** لاستخلاص عناوين الأخبار "
        "وروابطها وتواريخها. يُمنع منعًا باتًا إضافة أي عنوان أو رابط أو تاريخ أو "
        "اسم مجلة أو DOI غير موجود حرفيًا في هذه القائمة (قاعدة الدقة، القسم "
        "14). إذا لم تجد ضمن القائمة نتيجة تستوفي معايير القسمين 4 و5 لمجال "
        "معين، أو كان تاريخ النشر خارج النطاق الزمني المطلوب أو غير قابل "
        "للتحقق، فاكتب لهذا المجال العبارة المحددة في القسم 8 "
        "(\"لا توجد أخبار بحثية بارزة ضمن هذا المجال خلال الفترة المحددة.\") "
        "ولا تخترع شيئًا.\n\n"
        "<SEARCH_RESULTS>\n"
        f"{search_pool_text}\n"
        "</SEARCH_RESULTS>\n\n"
        "الآن نفّذ المهمة: صفِّ نتائج البحث أعلاه وفق معايير التعليمات كاملة "
        "(الأقسام 4، 5، 6، 7، 8، 9، 10، 12، 13، 14)، ثم أخرج **التقرير النهائي "
        "فقط** بصيغة Markdown مطابقة تمامًا للهيكل المحدد في القسم 11 من "
        "التعليمات — بلا أي مقدمة أو تعليق أو خاتمة خارج ذلك الهيكل، وبدون ذكر "
        "أنك استخدمت نتائج بحث مُجهَّزة مسبقًا."
    )


def _send_message_with_retry(chat, message: str):
    """يرسل رسالة إلى Gemini، ويعيد المحاولة تلقائيًا عند خطأ خادم مؤقت
    (503 UNAVAILABLE بسبب ضغط مؤقت على النموذج) بدل الفشل الفوري — مهم
    لأن التشغيل الأسبوعي عبر GitHub Actions لا يوجد فيه إنسان لإعادة
    الضغط على 'Run workflow' يدويًا."""

    last_exc: Exception | None = None
    for attempt, delay in enumerate([0] + GEMINI_SERVER_RETRY_DELAYS, start=1):
        if delay:
            print(
                f"  انتظار {delay} ثانية قبل إعادة المحاولة رقم {attempt} "
                "بسبب ضغط مؤقت على خادم Gemini (503) ...",
                file=sys.stderr,
            )
            time.sleep(delay)
        try:
            return chat.send_message(message)
        except genai_errors.ServerError as exc:
            last_exc = exc
            print(f"تحذير: خطأ خادم مؤقت من Gemini (محاولة {attempt}): {exc}", file=sys.stderr)
            continue
    raise last_exc  # type: ignore[misc]


def run_research_agent(client: genai.Client, model: str, system_prompt: str, user_prompt: str) -> str:
    """يشغّل Gemini لفرز نتائج Tavily الحقيقية والتحقق منها وتنسيقها فقط —
    بدون أي أداة بحث مدمجة (google_search غير متاحة على الخطة المجانية).
    يتابع تلقائيًا إن توقف الرد بسبب تجاوز الحد الأقصى للمخرجات
    (finish_reason == 'MAX_TOKENS')."""

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )
    chat = client.chats.create(model=model, config=config)

    collected_text: list[str] = []
    message = user_prompt

    for round_index in range(MAX_CONTINUATION_ROUNDS):
        response = _send_message_with_retry(chat, message)
        text = getattr(response, "text", None) or ""
        collected_text.append(text)

        finish_reason = None
        try:
            finish_reason = response.candidates[0].finish_reason
        except (AttributeError, IndexError, TypeError):
            pass
        finish_reason_name = getattr(finish_reason, "name", str(finish_reason))

        print(
            f"[round {round_index + 1}] finish_reason={finish_reason_name} "
            f"chars={len(text)}",
            file=sys.stderr,
        )

        if finish_reason_name in ("STOP", "None", None):
            break
        if finish_reason_name == "MAX_TOKENS":
            message = CONTINUE_PROMPT
            continue

        print(
            f"تحذير: توقف غير متوقع (finish_reason={finish_reason_name}) — "
            "سيُستخدم ما تم إنتاجه حتى الآن.",
            file=sys.stderr,
        )
        break
    else:
        print("تحذير: تم بلوغ الحد الأقصى لجولات المتابعة قبل انتهاء البحث.", file=sys.stderr)

    final_report = "\n".join(t for t in collected_text if t.strip())
    if not final_report.strip():
        sys.exit("لم يُنتج الوكيل أي نص نهائي — تحقق من سجلات الاستجابة أعلاه.")
    return final_report


def save_report(markdown_text: str, end: dt.date) -> pathlib.Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / f"{end.isoformat()}.md"
    out_path.write_text(markdown_text, encoding="utf-8")
    return out_path


def find_category_id(wp_url: str, auth: tuple[str, str], category_name: str) -> int | None:
    try:
        resp = requests.get(
            f"{wp_url.rstrip('/')}/wp-json/wp/v2/categories",
            params={"search": category_name},
            auth=auth,
            timeout=30,
        )
        resp.raise_for_status()
        results = resp.json()
        for cat in results:
            if cat.get("name") == category_name:
                return cat.get("id")
        return results[0]["id"] if results else None
    except requests.RequestException as exc:
        print(f"تحذير: تعذّر البحث عن التصنيف '{category_name}': {exc}", file=sys.stderr)
        return None


BARE_URL_PATTERN = re.compile(r"(?<![<(])\bhttps?://[^\s<>()\[\]]+")


def linkify_bare_urls(markdown_text: str) -> str: return BARE_URL_PATTERN.sub(lambda m: f"<{m.group(0)}>", markdown_text)
    

LEADING_TITLE_PATTERN = re.compile(r"\A\s*#\s.*?(?=^##\s)", re.S | re.M)


def strip_leading_title_block(markdown_text: str) -> str: return LEADING_TITLE_PATTERN.sub("", markdown_text, count=1)
    

def publish_to_wordpress(
    markdown_text: str,
    start: dt.date,
    end: dt.date,
    wp_url: str,
    wp_user: str,
    wp_app_password: str,
    category_name: str,
    status: str,
) -> dict:
    html_content = md.markdown(linkify_bare_urls(strip_leading_title_block(markdown_text)), extensions=["extra", "sane_lists"])
    title = f"نبض الأبحاث — النشرة البحثية الأسبوعية ({start.isoformat()} – {end.isoformat()})"

    auth = (wp_user, wp_app_password)
    category_id = find_category_id(wp_url, auth, category_name)

    payload = {
        "title": title,
        "content": html_content,
        "status": status,
    }
    if category_id:
        payload["categories"] = [category_id]

    resp = requests.post(
        f"{wp_url.rstrip('/')}/wp-json/wp/v2/posts",
        auth=auth,
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def main() -> None:
    api_key = os.environ.get("GEMINI_API_KEY")
    tavily_api_key = os.environ.get("TAVILY_API_KEY")
    wp_url = os.environ.get("WP_URL")
    wp_user = os.environ.get("WP_USER")
    wp_app_password = os.environ.get("WP_APP_PASSWORD")

    missing = [
        name
        for name, val in [
            ("GEMINI_API_KEY", api_key),
            ("TAVILY_API_KEY", tavily_api_key),
            ("WP_URL", wp_url),
            ("WP_USER", wp_user),
            ("WP_APP_PASSWORD", wp_app_password),
        ]
        if not val
    ]
    if missing:
        sys.exit(f"متغيرات بيئة ناقصة: {', '.join(missing)}")

    # ملاحظة: نستخدم `or` بدل الوسيط الثاني في os.environ.get لأن GitHub
    # Actions يمرّر متغيرات `vars.*` غير المُعرَّفة كسلسلة فارغة "" (وليس
    # قيمة غائبة)، و os.environ.get(key, default) لا يستبدل القيمة الفارغة
    # بالافتراضي لأن المفتاح موجود فعليًا (فقط فارغ).
    model = os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
    category_name = os.environ.get("WP_CATEGORY_NAME") or DEFAULT_CATEGORY_NAME
    status = os.environ.get("PUBLISH_STATUS") or "draft"
    lookback_days = int(os.environ.get("LOOKBACK_DAYS") or DEFAULT_LOOKBACK_DAYS)

    end = dt.datetime.now(dt.timezone.utc).date()
    start = end - dt.timedelta(days=lookback_days)

    system_prompt = load_instructions()

    print("جلب نتائج بحث حقيقية عبر Tavily لكل مجال من المجالات الاثني عشر ...", file=sys.stderr)
    search_pool = gather_search_pool(tavily_api_key, lookback_days)
    total_results = sum(len(v) for v in search_pool.values())
    print(f"إجمالي نتائج البحث الفريدة المجمَّعة: {total_results}", file=sys.stderr)
    search_pool_text = format_search_pool(search_pool)

    user_prompt = build_user_prompt(start, end, lookback_days, search_pool_text)

    client = genai.Client(api_key=api_key)

    print("بدء الفرز والتحقق والتنسيق عبر Gemini ...", file=sys.stderr)
    report_markdown = run_research_agent(client, model, system_prompt, user_prompt)

    out_path = save_report(report_markdown, end)
    print(f"تم حفظ التقرير في: {out_path}", file=sys.stderr)

    print(f"نشر مسودة على ووردبريس بحالة '{status}' ...", file=sys.stderr)
    post = publish_to_wordpress(
        report_markdown, start, end, wp_url, wp_user, wp_app_password, category_name, status
    )

    post_id = post.get("id")
    edit_link = f"{wp_url.rstrip('/')}/wp-admin/post.php?post={post_id}&action=edit"
    print(f"تم إنشاء المقالة رقم {post_id} بحالة '{status}'.", file=sys.stderr)
    print(f"رابط التحرير: {edit_link}", file=sys.stderr)


if __name__ == "__main__":
    main()
