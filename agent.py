#!/usr/bin/env python3
"""
وكيل رصد أخبار الفيزياء البحثية — آفاق فيزيائية
=================================================

يبحث أسبوعيًا في مصادر الفيزياء الموثوقة (APS, Nature, Physics World,
EurekAlert, المختبرات والجامعات الكبرى...) عن آخر 7 أيام من الأخبار
البحثية ضمن 12 مجالًا فيزيائيًا محددًا في instructions.md، يتحقق من كل
خبر عبر أداة web_search الحقيقية (بدون اختلاق أي معلومة)، ثم يبني
النشرة بصيغة Markdown مطابقة للقالب المطلوب، ويحفظها في reports/ وينشرها
كمسودة (draft) على ووردبريس للمراجعة قبل النشر الفعلي.

هذا السكربت مصمم للتشغيل داخل GitHub Actions (انظر
.github/workflows/weekly-radar.yml) لكنه يعمل محليًا كذلك.

المتغيرات البيئية المطلوبة:
    ANTHROPIC_API_KEY   مفتاح Anthropic API
    WP_URL              رابط الموقع، مثل: https://phy-lab.com
    WP_USER             اسم مستخدم ووردبريس (له صلاحية نشر)
    WP_APP_PASSWORD     كلمة مرور تطبيق ووردبريس (Application Password)

متغيرات اختيارية:
    ANTHROPIC_MODEL     معرّف النموذج (افتراضي أدناه — تحقق من
                         https://docs.claude.com/en/docs/about-claude/models
                         لأحدث معرّف عند الحاجة)
    WP_CATEGORY_NAME    اسم تصنيف ووردبريس المستهدف (افتراضي: "نبض الأبحاث")
    PUBLISH_STATUS      "draft" (افتراضي) أو "publish"
    LOOKBACK_DAYS       عدد الأيام للبحث (افتراضي: 7)
"""

from __future__ import annotations

import datetime as dt
import os
import pathlib
import sys

import anthropic
import markdown as md
import requests

REPO_ROOT = pathlib.Path(__file__).resolve().parent
INSTRUCTIONS_PATH = REPO_ROOT / "instructions.md"
REPORTS_DIR = REPO_ROOT / "reports"

DEFAULT_MODEL = "claude-sonnet-4-5-20250929"
DEFAULT_CATEGORY_NAME = "نبض الأبحاث"
DEFAULT_LOOKBACK_DAYS = 7
MAX_OUTPUT_TOKENS = 8000
MAX_WEB_SEARCH_USES = 40
# سقف أمان لعدد جولات المتابعة عند توقف الاستجابة بسبب طول البحث (pause_turn)
MAX_CONTINUATION_ROUNDS = 12


def load_instructions() -> str:
    if not INSTRUCTIONS_PATH.exists():
        sys.exit(f"لم يتم العثور على ملف التعليمات: {INSTRUCTIONS_PATH}")
    return INSTRUCTIONS_PATH.read_text(encoding="utf-8")


def build_user_prompt(start: dt.date, end: dt.date, lookback_days: int) -> str:
    return (
        f"التاريخ الحالي هو: {end.isoformat()}.\n"
        f"النطاق الزمني المطلوب لهذا التشغيل الأسبوعي هو آخر {lookback_days} أيام: "
        f"من {start.isoformat()} إلى {end.isoformat()} (التزم بهذا النطاق حرفيًا، "
        "ولا تعتمد على تقديرك الخاص لليوم أو الأسبوع).\n\n"
        "نفّذ المهمة كاملة الآن وفق تعليمات النظام: ابحث في المجالات الاثني عشر عبر "
        "أداة web_search الفعلية، تحقق من كل خبر (العنوان الأصلي، تاريخ النشر، المصدر، "
        "البحث الأصلي إن وجد، DOI إن وجد)، ثم أخرج **التقرير النهائي فقط** بصيغة "
        "Markdown مطابقة تمامًا للهيكل المحدد في القسم 11 من التعليمات — بلا أي مقدمة "
        "أو تعليق أو خاتمة خارج ذلك الهيكل."
    )


def run_research_agent(client: anthropic.Anthropic, model: str, system_prompt: str, user_prompt: str) -> str:
    """يشغّل الوكيل مع أداة web_search الخادمية، ويتابع تلقائيًا إن توقفت
    الاستجابة بسبب طول عملية البحث (stop_reason == 'pause_turn')."""

    messages: list[dict] = [{"role": "user", "content": user_prompt}]
    collected_text: list[str] = []

    for round_index in range(MAX_CONTINUATION_ROUNDS):
        response = client.messages.create(
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=system_prompt,
            tools=[
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": MAX_WEB_SEARCH_USES,
                }
            ],
            messages=messages,
        )

        for block in response.content:
            if getattr(block, "type", None) == "text":
                collected_text.append(block.text)

        print(
            f"[round {round_index + 1}] stop_reason={response.stop_reason} "
            f"blocks={[getattr(b, 'type', '?') for b in response.content]}",
            file=sys.stderr,
        )

        if response.stop_reason != "pause_turn":
            break

        # أكمل المحادثة من حيث توقفت (نمط موثّق للبحث الطويل عبر web_search)
        messages.append({"role": "assistant", "content": response.content})
        messages.append(
            {
                "role": "user",
                "content": (
                    "تابع البحث والتحقق من حيث توقفت تمامًا، دون إعادة كتابة أي جزء "
                    "سبق أن أنتجته، حتى تكمل التقرير النهائي الكامل."
                ),
            }
        )
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
    html_content = md.markdown(markdown_text, extensions=["extra", "sane_lists"])
    title = f"آفاق فيزيائية — النشرة البحثية الأسبوعية ({start.isoformat()} – {end.isoformat()})"

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
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    wp_url = os.environ.get("WP_URL")
    wp_user = os.environ.get("WP_USER")
    wp_app_password = os.environ.get("WP_APP_PASSWORD")

    missing = [
        name
        for name, val in [
            ("ANTHROPIC_API_KEY", api_key),
            ("WP_URL", wp_url),
            ("WP_USER", wp_user),
            ("WP_APP_PASSWORD", wp_app_password),
        ]
        if not val
    ]
    if missing:
        sys.exit(f"متغيرات بيئة ناقصة: {', '.join(missing)}")

    model = os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)
    category_name = os.environ.get("WP_CATEGORY_NAME", DEFAULT_CATEGORY_NAME)
    status = os.environ.get("PUBLISH_STATUS", "draft")
    lookback_days = int(os.environ.get("LOOKBACK_DAYS", DEFAULT_LOOKBACK_DAYS))

    end = dt.datetime.now(dt.timezone.utc).date()
    start = end - dt.timedelta(days=lookback_days)

    system_prompt = load_instructions()
    user_prompt = build_user_prompt(start, end, lookback_days)

    client = anthropic.Anthropic(api_key=api_key)

    print("بدء البحث والتحقق عبر web_search ...", file=sys.stderr)
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
