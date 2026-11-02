"""تحويل تقرير "نبض الأبحاث" (Markdown بقالب القسم 11 من instructions.md) إلى
كتلة HTML بهوية موقع معامل الفيزياء phy-lab.com لنشرها في ووردبريس.

المبادئ:
- ملف reports/*.md لا يُمسّ؛ هذا التحويل يحدث عند النشر فقط.
- لا يُعاد صياغة أي عنوان أو قيمة: كل نص يُنقل حرفيًا (مع تهريب HTML فقط).
- المحلّل بنيوي (## مجال / ### خبر / **مفتاح:** قيمة)، لا يعتمد على ترتيب
  ثابت للمجالات أو الحقول؛ وإن فشل التعرّف على البنية يرجع None ليستعمل
  المستدعي التحويل العادي عبر مكتبة markdown.
- المخرج سطر واحد بلا أسطر فارغة (wpautop)، ملفوف في كتلة HTML مخصص
  لمحرر Gutenberg، وكل محددات CSS تبدأ بـ .pl-pulse حتى لا تمسّ القالب.
"""

from __future__ import annotations

import datetime as dt
import html
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

SLUG = "pl-pulse"

EMPTY_MARKER = "لا توجد أخبار بحثية بارزة"

# ---------------------------------------------------------------- الرموز
# رموز خطية 24×24 (stroke=currentColor). تُختار بالكلمات المفتاحية في عنوان
# المجال، فلا يرتبط الرمز بترتيب المجالات أو بالإيموجي المستعمل في التقرير.
_ICONS: list[tuple[tuple[str, ...], str]] = [
    # الطاقة: شمس فوق خلية شمسية مخططة
    (("الطاقة", "energy"),
     '<circle cx="12" cy="8" r="3.2"/><path d="M12 1.8v1.6M5.6 8H4M20 8h-1.6M7.3 3.3l1.1 1.1M16.7 3.3l-1.1 1.1"/>'
     '<path d="M4 15.5h16l-1.6 6H5.6z"/><path d="M9.3 15.5l-.6 6M14.7 15.5l.6 6M4.8 18.5h14.4"/>'),
    # أشباه الموصلات: شريحة بأطراف
    (("أشباه الموصلات", "semiconductor"),
     '<rect x="6.5" y="6.5" width="11" height="11" rx="1"/><rect x="9.5" y="9.5" width="5" height="5"/>'
     '<path d="M9.5 2.5v4M14.5 2.5v4M9.5 17.5v4M14.5 17.5v4M2.5 9.5h4M2.5 14.5h4M17.5 9.5h4M17.5 14.5h4"/>'),
    # البلازما والاندماج: مقطع توكاماك (حلقتان) مع خط مجال
    (("البلازما", "الاندماج", "plasma", "fusion"),
     '<ellipse cx="12" cy="12" rx="9.5" ry="5"/><ellipse cx="12" cy="12" rx="4.2" ry="1.9"/>'
     '<path d="M3.2 10.2c3 2.4 14.6 2.4 17.6 0"/>'),
    # البوليمرات: سلسلة متعرجة من وحدات
    (("البوليمرات", "اللينة", "polymer"),
     '<path d="M2.5 15l3.8-6 3.8 6 3.8-6 3.8 6 3.8-6"/><circle cx="6.3" cy="9" r="1.3"/>'
     '<circle cx="13.9" cy="9" r="1.3"/><circle cx="10.1" cy="15" r="1.3"/><circle cx="17.7" cy="15" r="1.3"/>'),
    # المواد المتقدمة: شبكة سداسية (جرافين)
    (("المواد المتقدمة", "advanced materials"),
     '<path d="M8 3.5l4 2.3v4.6l-4 2.3-4-2.3V5.8z"/><path d="M16 8.1l4 2.3v4.6l-4 2.3-4-2.3v-4.6"/>'
     '<path d="M8 12.7v4.6l4 2.3 4-2.3"/>'),
    # الكم: كرة بلوخ
    (("الكم", "quantum"),
     '<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="9" ry="3.2"/>'
     '<path d="M12 12l4.6-6.2"/><circle cx="16.6" cy="5.8" r="1.3"/>'),
    # النانو: نقاط كمّية متدرجة الحجم
    (("النانو", "nano"),
     '<rect x="3" y="3" width="18" height="18" rx="1.5"/><circle cx="8" cy="8" r="1"/><circle cx="16" cy="8" r="1.6"/>'
     '<circle cx="8" cy="16" r="2.1"/><circle cx="16" cy="16" r="2.7"/>'),
    # الفوتونيات: موجة تمر عبر عدسة
    (("الفوتونيات", "البصريات", "photonic", "optic"),
     '<path d="M12 3c2.2 2.6 2.2 15.4 0 18M12 3c-2.2 2.6-2.2 15.4 0 18"/>'
     '<path d="M1.5 12c1-2.4 2-2.4 3 0s2 2.4 3 0M16.5 12c1-2.4 2-2.4 3 0s2 2.4 3 0"/>'),
    # المادة المكثفة: خلية مكعبة
    (("المادة المكثفة", "condensed"),
     '<path d="M4 8h11v11H4z"/><path d="M4 8l5-4.5h11L15 8M20 3.5v11L15 19"/>'
     '<circle cx="4" cy="8" r="1.2"/><circle cx="15" cy="8" r="1.2"/><circle cx="4" cy="19" r="1.2"/><circle cx="15" cy="19" r="1.2"/>'),
    # النووية والجسيمات: مسارات جسيمات منحنية من نقطة تصادم
    (("النووية", "الجسيمات", "nuclear", "particle"),
     '<circle cx="12" cy="13" r="1.6"/><path d="M12 13c-3-1-6.5-4.8-7.5-9.5M12 13c3.5-.5 7.5-3 9-7.5"/>'
     '<path d="M12 13c-1.8 2.8-5.6 5.8-9 7M12 13c2 3 3 5.6 3.3 8.5"/>'),
    # الفلك والكونيات: كوكب ذو حلقة
    (("الفلكية", "الكونيات", "astro", "cosmo"),
     '<circle cx="12" cy="12" r="5.5"/><path d="M6.2 13.9C2.6 16 1.4 17.7 2 18.6c1 1.6 7.4-.6 13.2-4.3S23 6.9 22 5.4c-.6-.9-2.6-.6-5.4.7"/>'),
    # الذكاء الاصطناعي: شبكة عصبية
    (("الذكاء", "الحوسبة", "ai ", "machine"),
     '<circle cx="4.5" cy="7" r="1.6"/><circle cx="4.5" cy="17" r="1.6"/><circle cx="12" cy="4.5" r="1.6"/>'
     '<circle cx="12" cy="12" r="1.6"/><circle cx="12" cy="19.5" r="1.6"/><circle cx="19.5" cy="12" r="1.6"/>'
     '<path d="M6 7.6l4.5-2.4M6 7.8l4.5 3.6M6 16.2l4.5-3.6M6 16.4l4.5 2.4M13.6 4.9l4.6 6.2M13.6 12h4.3M13.6 19.1l4.6-6.2"/>'),
]
_FALLBACK_ICON = '<circle cx="12" cy="12" r="8"/><path d="M8 12h8"/>'


def _icon(title: str) -> str:
    low = title.lower()
    body = next((svg for keys, svg in _ICONS if any(k in low for k in keys)), _FALLBACK_ICON)
    return (
        '<svg class="pl-pulse__ic" viewBox="0 0 24 24" width="22" height="22" fill="none" '
        'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true" focusable="false">{body}</svg>'
    )


# ---------------------------------------------------------------- التحليل
@dataclass
class Item:
    title: str
    fields: dict[str, str] = field(default_factory=dict)


@dataclass
class Domain:
    title: str
    items: list[Item] = field(default_factory=list)
    empty_note: str | None = None


_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍⃣]+"
)
_FIELD_RE = re.compile(r"^\s*(?:[-*]\s*)?\*\*\s*([^*:：]+?)\s*[:：]\s*\*\*\s*(.*?)\s*$")
_FIELD_RE_ALT = re.compile(r"^\s*(?:[-*]\s*)?\*\*\s*([^*]+?)\s*\*\*\s*[:：]\s*(.*?)\s*$")
_ITEM_NUM_RE = re.compile(r"^\s*\d+\s*[.)\-–]\s*")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")
_ANGLE_RE = re.compile(r"^<(https?://[^>\s]+)>$")


def _clean_inline(text: str) -> str:
    """يزيل علامات Markdown الشكلية فقط (لا يغيّر الكلمات)."""
    text = _MD_LINK_RE.sub(lambda m: m.group(1) or m.group(2), text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text.strip()


def _field_value(raw: str) -> str:
    raw = raw.strip()
    m = _ANGLE_RE.match(raw)
    if m:
        return m.group(1)
    m = _MD_LINK_RE.fullmatch(raw)
    if m:
        return m.group(2)
    return _clean_inline(raw)


def parse_report(markdown_text: str) -> list[Domain]:
    domains: list[Domain] = []
    cur_d: Domain | None = None
    cur_i: Item | None = None
    for line in markdown_text.splitlines():
        s = line.strip()
        if not s or re.fullmatch(r"[-*_]{3,}", s):
            continue
        if s.startswith("## ") and not s.startswith("### "):
            title = _EMOJI_RE.sub("", s[3:]).strip()
            cur_d, cur_i = Domain(title=_clean_inline(title)), None
            domains.append(cur_d)
            continue
        if cur_d is None:
            continue  # رأس التقرير (H1 + الفترة) — يُبنى رأس مستقل بدلاً منه
        if s.startswith("### "):
            cur_i = Item(title=_clean_inline(_ITEM_NUM_RE.sub("", s[4:], count=1)))
            cur_d.items.append(cur_i)
            continue
        m = _FIELD_RE.match(s) or _FIELD_RE_ALT.match(s)
        if m and cur_i is not None:
            key, val = m.group(1).strip(), _field_value(m.group(2))
            if val:
                cur_i.fields[key] = val
            continue
        if EMPTY_MARKER in s and not cur_d.items:
            cur_d.empty_note = _clean_inline(s.lstrip(">").strip())
    return domains


# ---------------------------------------------------------------- العرض
_UNKNOWN = {"", "غير محدد", "غير متوفر", "غير متاح", "لا يوجد", "n/a", "na", "none", "-", "—"}


def _known(v: str | None) -> bool:
    return bool(v) and v.strip().lower() not in _UNKNOWN


def _get(fields: dict[str, str], *keys: str) -> str | None:
    for k in keys:
        for fk, fv in fields.items():
            if fk.replace(" ", "").lower() == k.replace(" ", "").lower():
                return fv if _known(fv) else None
    return None


def _safe_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip().rstrip(".,;،")
    p = urlparse(url)
    if p.scheme in ("http", "https") and p.netloc:
        return url
    return None


def _host(url: str) -> str:
    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _doi_url(doi: str) -> str | None:
    m = re.search(r"10\.\d{4,9}/\S+", doi)
    return f"https://doi.org/{m.group(0).rstrip('.,;')}" if m else None


def _e(t: str) -> str:
    return html.escape(t, quote=True)


def _is_rtl(t: str) -> bool:
    return bool(re.search(r"[؀-ۿ]", t))


def _pair(label: str, value_html: str) -> str:
    return f'<span class="pl-pulse__kv"><span class="pl-pulse__k">{label}</span>{value_html}</span>'


def _render_item(idx: int, it: Item) -> str:
    url = _safe_url(_get(it.fields, "الرابط", "Link", "URL"))
    src = _get(it.fields, "المصدر", "Source")
    date = _get(it.fields, "تاريخ النشر", "التاريخ", "Date")
    journal = _get(it.fields, "البحث الأصلي", "المجلة", "Journal")
    doi = _get(it.fields, "DOI")

    title_dir = "rtl" if _is_rtl(it.title) else "ltr"
    t = _e(it.title)
    title_html = (
        f'<a href="{_e(url)}" target="_blank" rel="noopener">{t}</a>' if url else t
    )
    pairs = []
    if src:
        pairs.append(_pair("المصدر", f'<bdi class="pl-pulse__v">{_e(src)}</bdi>'))
    if date:
        pairs.append(_pair("النشر", f'<bdi class="pl-pulse__v pl-pulse__mono">{_e(date)}</bdi>'))
    if journal and (not src or journal.strip().lower() != src.strip().lower()):
        pairs.append(_pair("البحث الأصلي", f'<bdi class="pl-pulse__v">{_e(journal)}</bdi>'))
    if doi:
        du = _doi_url(doi)
        v = (f'<a class="pl-pulse__v pl-pulse__mono" dir="ltr" href="{_e(du)}" target="_blank" rel="noopener">{_e(doi)}</a>'
             if du else f'<bdi class="pl-pulse__v pl-pulse__mono">{_e(doi)}</bdi>')
        pairs.append(_pair("DOI", v))
    if url:
        pairs.append(_pair("الرابط", f'<a class="pl-pulse__v pl-pulse__mono" dir="ltr" href="{_e(url)}" '
                                     f'target="_blank" rel="noopener">{_e(_host(url))}</a>'))
    return (
        f'<article class="pl-pulse__item"><span class="pl-pulse__n" aria-hidden="true">{idx}</span>'
        f'<div class="pl-pulse__body"><h4 class="pl-pulse__t" dir="{title_dir}">{title_html}</h4>'
        f'<p class="pl-pulse__meta">{"".join(pairs)}</p></div></article>'
    )


def _render_domain(i: int, d: Domain) -> str:
    n = len(d.items)
    head = (
        f'<header class="pl-pulse__dh">{_icon(d.title)}<h3 class="pl-pulse__dt">{_e(d.title)}</h3></header>'
    )
    if n:
        body = "".join(_render_item(k + 1, it) for k, it in enumerate(d.items))
    else:
        note = d.empty_note or "لا توجد أخبار بحثية بارزة ضمن هذا المجال خلال الفترة المحددة."
        body = f'<p class="pl-pulse__empty">{_e(note)}</p>'
    return f'<section class="pl-pulse__d" id="{SLUG}-d{i}" aria-label="{_e(d.title)}">{head}{body}</section>'


def _render_header(domains: list[Domain], start: dt.date, end: dt.date) -> str:
    total = sum(len(d.items) for d in domains)
    active = sum(1 for d in domains if d.items)
    idx = "".join(
        f'<a class="pl-pulse__ix{"" if d.items else " is-empty"}" href="#{SLUG}-d{i}">'
        f'{_icon(d.title)}<span class="pl-pulse__ixn">{_e(d.title)}</span>'
        f'<span class="pl-pulse__ixc pl-pulse__mono">{len(d.items) if d.items else "—"}</span></a>'
        for i, d in enumerate(domains, 1)
    )
    return (
        '<header class="pl-pulse__h">'
        '<div class="pl-pulse__stats">'
        f'<div class="pl-pulse__st"><span class="pl-pulse__k">الفترة</span>'
        f'<span class="pl-pulse__sv pl-pulse__mono" dir="ltr">{start.isoformat()} – {end.isoformat()}</span></div>'
        f'<div class="pl-pulse__st"><span class="pl-pulse__k">الأخبار</span>'
        f'<span class="pl-pulse__sv pl-pulse__mono">{total}</span></div>'
        f'<div class="pl-pulse__st"><span class="pl-pulse__k">المجالات النشطة</span>'
        f'<span class="pl-pulse__sv pl-pulse__mono" dir="ltr">{active}/{len(domains)}</span></div>'
        '</div>'
        f'<nav class="pl-pulse__index" aria-label="مجالات النشرة">{idx}</nav>'
        '</header>'
    )


_CSS = """
section.pl-pulse{--phy-ink:#05264B;--phy-deep:#1D3C70;--phy-steel:#4A73A6;--phy-sky:#6192C3;--phy-glow:#6CBADD;--phy-mist:#DCE7F2;--phy-haze:#EEF3F8;--phy-paper:#F7F9FB;--phy-white:#FFFFFF;--phy-slate:#4B5B6E;--phy-rule:#B9CADC;
--pl-bg:var(--phy-white);--pl-fg:var(--phy-ink);--pl-sub:var(--phy-slate);--pl-link:var(--phy-deep);--pl-acc:var(--phy-steel);--pl-soft:var(--phy-haze);--pl-line:var(--phy-rule);
font-family:"Tosh A","IBM Plex Sans Arabic","STIX Two Text",sans-serif;color:var(--pl-fg);font-size:17px;line-height:1.85;direction:rtl;text-align:right;-webkit-text-size-adjust:100%;margin:0 0 2rem;padding:0;border:0;background:transparent;box-shadow:none;max-width:100%}
.dark-skin section.pl-pulse,section.pl-pulse.is-dark{--pl-fg:#EEF3F8;--pl-sub:#A9BACD;--pl-link:#9CC6EA;--pl-acc:#6CBADD;--pl-soft:rgba(220,231,242,.06);--pl-line:rgba(185,202,220,.22)}
section.pl-pulse *{box-sizing:border-box}
section.pl-pulse section,section.pl-pulse header,section.pl-pulse nav,section.pl-pulse article{margin:0;border:0;background:transparent;box-shadow:none;padding:0;float:none;width:auto}
section.pl-pulse [hidden]{display:none!important}
section.pl-pulse .pl-pulse__mono{font-family:"JetBrains Mono",ui-monospace,Menlo,Consolas,monospace;font-weight:400;font-size:.86em;letter-spacing:0}
section.pl-pulse h3,section.pl-pulse h4{margin:0;padding:0;border:0;background:none;text-transform:none;letter-spacing:0;font-family:inherit;color:var(--pl-fg)}
section.pl-pulse h3:before,section.pl-pulse h3:after,section.pl-pulse h4:before,section.pl-pulse h4:after{display:none!important;content:none!important}
section.pl-pulse p{margin:0;padding:0}
section.pl-pulse a{color:var(--pl-link);text-decoration:none;box-shadow:none;border:0}
section.pl-pulse a:focus-visible{outline:2px solid var(--phy-glow);outline-offset:2px;border-radius:2px}
section.pl-pulse .pl-pulse__ic{flex:none;width:22px;height:22px;color:var(--pl-acc)}
section.pl-pulse .pl-pulse__h{background:var(--pl-soft);border-top:3px solid var(--phy-ink);padding:20px 22px 18px;margin:0 0 8px}
.dark-skin section.pl-pulse .pl-pulse__h{border-top-color:var(--phy-glow)}
section.pl-pulse .pl-pulse__stats{display:flex;flex-wrap:wrap;gap:12px 40px;padding-bottom:16px;border-bottom:1px solid var(--pl-line);margin-bottom:12px}
section.pl-pulse .pl-pulse__st{display:flex;flex-direction:column;gap:2px}
section.pl-pulse .pl-pulse__k{color:var(--pl-sub);font-size:13px;line-height:1.5;font-weight:500}
section.pl-pulse .pl-pulse__sv{font-size:20px;line-height:1.4;color:var(--pl-fg);white-space:nowrap}
section.pl-pulse .pl-pulse__index{display:grid;grid-template-columns:1fr 1fr;column-gap:28px}
section.pl-pulse .pl-pulse__ix{display:flex;align-items:center;gap:10px;min-height:44px;padding:6px 0;border-bottom:1px solid var(--pl-line);color:var(--pl-fg);font-size:15px;line-height:1.45}
section.pl-pulse .pl-pulse__ix .pl-pulse__ic{width:18px;height:18px}
section.pl-pulse .pl-pulse__ixn{flex:1;min-width:0}
section.pl-pulse .pl-pulse__ixc{color:var(--pl-sub);min-width:1.5em;text-align:left}
section.pl-pulse .pl-pulse__ix:hover .pl-pulse__ixn{color:var(--pl-link);text-decoration:underline;text-underline-offset:4px}
section.pl-pulse .pl-pulse__ix.is-empty{color:var(--pl-sub)}
section.pl-pulse .pl-pulse__ix.is-empty .pl-pulse__ic{opacity:.55}
section.pl-pulse .pl-pulse__d{padding:34px 0 6px;scroll-margin-top:96px}
section.pl-pulse .pl-pulse__dh{display:flex;align-items:center;gap:12px;padding-bottom:12px;border-bottom:1px solid var(--pl-fg)}
section.pl-pulse .pl-pulse__dt{flex:1;font-size:22px!important;line-height:1.35!important;font-weight:700!important;text-wrap:balance}
section.pl-pulse .pl-pulse__dc{color:var(--pl-sub);font-size:15px}
section.pl-pulse .pl-pulse__item{display:grid;grid-template-columns:28px 1fr;gap:0 10px;padding:16px 0 18px;border-bottom:1px solid var(--pl-line)}
section.pl-pulse .pl-pulse__n{font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-size:13px;line-height:1.9;color:var(--pl-acc);padding-top:2px}
section.pl-pulse .pl-pulse__body{min-width:0}
section.pl-pulse .pl-pulse__t{font-size:18px!important;line-height:1.5!important;font-weight:700!important;text-align:right;overflow-wrap:anywhere;text-wrap:pretty}
section.pl-pulse .pl-pulse__t[dir=ltr]{unicode-bidi:isolate}
section.pl-pulse .pl-pulse__t a{color:var(--pl-fg);background-image:linear-gradient(var(--pl-line),var(--pl-line));background-size:100% 1px;background-position:0 100%;background-repeat:no-repeat;transition:color .15s,background-size .15s}
section.pl-pulse .pl-pulse__t a:hover{color:var(--pl-link);background-image:linear-gradient(var(--pl-acc),var(--pl-acc))}
section.pl-pulse .pl-pulse__meta{display:flex;flex-wrap:wrap;gap:4px 22px;margin-top:8px;font-size:14px;line-height:1.6}
section.pl-pulse .pl-pulse__kv{display:inline-flex;align-items:baseline;gap:6px;min-width:0;max-width:100%}
section.pl-pulse .pl-pulse__kv .pl-pulse__k{font-size:13px}
section.pl-pulse .pl-pulse__meta .pl-pulse__mono{font-size:13.5px}
section.pl-pulse .pl-pulse__v{color:var(--pl-fg);overflow-wrap:anywhere;min-width:0}
section.pl-pulse a.pl-pulse__v{color:var(--pl-link);text-decoration:underline;text-decoration-color:var(--pl-line);text-underline-offset:3px}
section.pl-pulse a.pl-pulse__v:hover{text-decoration-color:currentColor}
section.pl-pulse .pl-pulse__empty{padding:16px 0 18px 0;color:var(--pl-sub);font-size:15px;border-bottom:1px solid var(--pl-line)}
section.pl-pulse .pl-pulse__foot{margin-top:26px;color:var(--pl-sub);font-size:13px;line-height:1.7}
@media (max-width:640px){
section.pl-pulse{font-size:16px}
section.pl-pulse .pl-pulse__h{padding:16px 16px 12px}
section.pl-pulse .pl-pulse__stats{gap:10px 26px}
section.pl-pulse .pl-pulse__sv{font-size:17px}
section.pl-pulse .pl-pulse__index{grid-template-columns:1fr}
section.pl-pulse .pl-pulse__dt{font-size:19px!important}
section.pl-pulse .pl-pulse__item{grid-template-columns:22px 1fr;gap:0 6px}
section.pl-pulse .pl-pulse__t{font-size:16.5px!important}
section.pl-pulse .pl-pulse__meta{gap:2px 16px}
}
@media (max-width:640px),(pointer:coarse){
section.pl-pulse .pl-pulse__t a{display:block;padding:10px 0;background-image:none}
section.pl-pulse a.pl-pulse__v{display:inline-flex;align-items:center;min-height:44px}
section.pl-pulse .pl-pulse__kv{align-items:center}
section.pl-pulse .pl-pulse__item{padding-top:6px}
section.pl-pulse .pl-pulse__n{padding-top:12px}
}
@media (prefers-reduced-motion:reduce){section.pl-pulse *{transition:none!important}}
"""


def _min_css(css: str) -> str:
    css = re.sub(r"\s*\n\s*", "", css)
    css = re.sub(r"\s*([{};,])\s*", r"\1", css)
    return css.strip()


FONT_LINK = (
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    'family=IBM+Plex+Sans+Arabic:wght@400;500;700&amp;family=JetBrains+Mono:wght@400&amp;display=swap">'
)


def render_wp_html(markdown_text: str, start: dt.date, end: dt.date) -> str | None:
    """يرجع HTML كتلة ووردبريس بهوية الموقع، أو None إن لم يُتعرّف على بنية
    القالب (ليستعمل المستدعي التحويل العادي)."""
    domains = parse_report(markdown_text)
    if not domains:
        return None
    body = "".join(_render_domain(i, d) for i, d in enumerate(domains, 1))
    foot = (
        '<p class="pl-pulse__foot">العناوين منقولة بلغتها الأصلية كما نشرها المصدر، '
        'وكل عنوان يفتح صفحة الخبر الأصلية.</p>'
    )
    inner = (
        f'<section class="{SLUG}" dir="rtl" lang="ar">{FONT_LINK}<style>{_min_css(_CSS)}</style>'
        f'{_render_header(domains, start, end)}{body}{foot}</section>'
    )
    assert "\n" not in inner
    return f"<!-- wp:html -->\n{inner}\n<!-- /wp:html -->"
