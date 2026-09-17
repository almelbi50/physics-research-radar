# وكيل "آفاق فيزيائية" — رادار الأخبار البحثية الأسبوعي

وكيل ذكاء اصطناعي يعمل أسبوعيًا عبر GitHub Actions:

1. يبحث فعليًا على الويب (أداة `web_search` من Anthropic) في المصادر العلمية
   الموثوقة (APS, Nature, Physics World, EurekAlert, CERN, MIT, Stanford...
   إلخ) عن آخر 7 أيام من الأخبار البحثية ضمن 12 مجالًا فيزيائيًا.
2. يتحقق من كل خبر (العنوان الأصلي، التاريخ، المصدر، DOI إن وجد) بدل
   الاعتماد على معرفة النموذج المخزّنة — التزامًا الصارم بتعليمات
   `instructions.md` (لا ترجمة، لا إعادة صياغة، لا اختلاق معلومات).
3. يحفظ النشرة الناتجة كملف Markdown داخل `reports/` ويرفعه (commit) إلى
   المستودع تلقائيًا.
4. ينشرها **كمسودة (draft)** على ووردبريس (phy-lab.com) ضمن تصنيف
   "آفاق فيزيائية" — لمراجعتك والنشر يدويًا، وليس نشرًا فوريًا مباشرًا.

هذا مستودع مستقل تمامًا عن أدوات الأتمتة الحالية (`auto_physics.py`،
`physics_pipeline.py`، `experiments_pipeline.py`) ولا يتعارض معها.

---

## 1. إنشاء المستودع على GitHub

1. أنشئ مستودعًا جديدًا فارغًا باسم مقترح `physics-research-radar` تحت
   حسابك (`github.com/almelbi50`).
2. ارفع محتويات هذه الحزمة إلى المستودع:

   ```bash
   cd physics-research-radar
   git init
   git add .
   git commit -m "إعداد وكيل رادار الأخبار البحثية الأسبوعي"
   git branch -M main
   git remote add origin https://github.com/almelbi50/physics-research-radar.git
   git push -u origin main
   ```

---

## 2. إعداد المفاتيح السرّية (Secrets)

في المستودع على GitHub: **Settings → Secrets and variables → Actions →
New repository secret**، أضف:

| الاسم | القيمة |
|---|---|
| `ANTHROPIC_API_KEY` | مفتاح Anthropic API الخاص بك (من console.anthropic.com) |
| `WP_URL` | `https://phy-lab.com` |
| `WP_USER` | اسم مستخدم ووردبريس الذي له صلاحية إنشاء مقالات |
| `WP_APP_PASSWORD` | كلمة مرور تطبيق ووردبريس (وليست كلمة مرور حسابك) |

### كيف تنشئ كلمة مرور تطبيق ووردبريس؟

في لوحة تحكم ووردبريس: **Users → Profile → Application Passwords** → أدخل
اسمًا مثل `physics-radar` → **Add New Application Password** → انسخ
القيمة الناتجة فورًا (لن تظهر مرة أخرى) واستخدمها في `WP_APP_PASSWORD`.

> تأكد أن REST API لووردبريس (`/wp-json/`) غير محجوب بجدار حماية أو إضافة
> أمان (بعض إضافات التقوية تمنع `wp-json` بشكل افتراضي).

### متغيرات اختيارية (Repository Variables، وليست Secrets)

في **Settings → Secrets and variables → Actions → Variables** يمكنك
ضبط، عند الحاجة فقط:

- `ANTHROPIC_MODEL` — لتحديد نموذج مختلف عن الافتراضي في `agent.py`.
  راجع القائمة المحدّثة في
  <https://docs.claude.com/en/docs/about-claude/models> بين حين وآخر،
  لأن معرّفات النماذج تتغير مع الوقت.
- `WP_CATEGORY_NAME` — إن أردت تصنيفًا مختلفًا عن "آفاق فيزيائية".
- `PUBLISH_STATUS` — غيّرها إلى `publish` لاحقًا إذا قررت النشر المباشر
  بدل المسودة (الإعداد الافتراضي حاليًا: مسودة للمراجعة).

---

## 3. التفعيل والتجربة

1. من تبويب **Actions** في المستودع، فعّل الـ workflows إذا طُلب ذلك.
2. جرّب التشغيل يدويًا أولًا: **Actions → Weekly Physics Research Radar
   → Run workflow**.
3. راقب السجل (logs) للتأكد من نجاح البحث والنشر.
4. افتح ووردبريس → **المقالات → المسودات** وستجد النشرة الجديدة جاهزة
   للمراجعة والنشر.
5. تحقق من `reports/` في المستودع — ستجد نسخة Markdown مؤرشفة من كل
   نشرة أسبوعية.

الجدولة الافتراضية: كل يوم اثنين الساعة 08:00 بتوقيت الرياض. لتغييرها،
عدّل سطر `cron` في
`.github/workflows/weekly-radar.yml` (استخدم <https://crontab.guru>
للمساعدة — تذكّر أن GitHub Actions يستخدم توقيت UTC).

---

## 4. ملاحظات مهمة

- **`instructions.md` هو مصدر الحقيقة**: أي تعديل تريده على نطاق البحث،
  المجالات، المصادر، أو قالب التقرير — عدّله في هذا الملف مباشرة دون
  الحاجة لتعديل الكود.
- الوكيل مُلزم صراحة (في نهاية `instructions.md`) بعدم اختلاق أي معلومة
  وباستخدام أداة `web_search` فعليًا للتحقق من كل خبر، لا الاعتماد على
  معرفته المخزّنة مسبقًا.
- الأسعار: كل تشغيل أسبوعي يستهلك استدعاءات Anthropic API (نموذج +
  استخدامات web_search) — راجع التسعير الحالي في console.anthropic.com
  قبل التفعيل الدائم.
- إذا لم يجد الوكيل تصنيف "آفاق فيزيائية" في ووردبريس عبر الـ REST API،
  سينشر المسودة بدون تصنيف ويكتب تحذيرًا في السجل — تحقّق حينها من اسم
  التصنيف الفعلي على الموقع.
