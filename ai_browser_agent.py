"""
برنامج ذكاء اصطناعي يفتح متصفح وينفذ المهمة اللي تكتبها بلغة طبيعية.

المتطلبات:
    pip install anthropic playwright
    playwright install chromium

التشغيل:
    export ANTHROPIC_API_KEY="your-key"      # على Windows: set ANTHROPIC_API_KEY=your-key
    python ai_browser_agent.py
"""

import json
import re

import anthropic
from playwright.sync_api import sync_playwright

MODEL = "claude-sonnet-5-5"
MAX_STEPS = 20

client = anthropic.Anthropic()  # بيقرأ ANTHROPIC_API_KEY تلقائيًا

SYSTEM_PROMPT = """أنت وكيل يتحكم في متصفح ويب لتنفيذ مهمة يطلبها المستخدم.
في كل خطوة هتشوف: المهمة، الرابط الحالي، نص الصفحة، وقائمة العناصر القابلة للتفاعل مع أرقامها (id).
ردك لازم يكون JSON فقط بدون أي شرح، بأحد الشكلين التاليين:

{"action": "goto", "url": "https://..."}
{"action": "click", "id": 5}
{"action": "type", "id": 3, "text": "النص", "enter": true}
{"action": "press", "key": "Enter"}
{"action": "scroll"}
{"action": "done", "answer": "الإجابة النهائية للمستخدم بالعربي"}

لو المهمة خلصت استخدم done. لو فيه خطأ في خطوة سابقة اتعمل تصحيح في الخطوة الجاية.
"""


def get_interactive_elements(page):
    """بيجيب العناصر القابلة للتفاعل ويعلّمها بـ data-ai-id عشان نقدر نوصلها بعدين."""
    return page.evaluate(
        """() => {
            const selector = 'a, button, input, textarea, select, [role=button]';
            const els = [...document.querySelectorAll(selector)].slice(0, 150);
            const result = [];
            els.forEach((el, i) => {
                el.setAttribute('data-ai-id', i);
                const text = (el.innerText || el.value || el.placeholder ||
                              el.getAttribute('aria-label') || '').trim().slice(0, 80);
                if (text || el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
                    result.push({ id: i, tag: el.tagName.toLowerCase(), text: text });
                }
            });
            return result;
        }"""
    )


def describe_page(page, task):
    """بيحضر حالة الصفحة الحالية عشان نبعتها للموديل."""
    try:
        body_text = page.inner_text("body")[:3000]
    except Exception:
        body_text = "(تعذر قراءة نص الصفحة)"

    elements = get_interactive_elements(page)
    return (
        f"المهمة: {task}\n"
        f"الرابط الحالي: {page.url}\n"
        f"نص الصفحة:\n{body_text}\n\n"
        f"العناصر القابلة للتفاعل:\n{json.dumps(elements, ensure_ascii=False)}"
    )


def ask_model(messages):
    """بيبعت الرسائل للموديل ويرجع الأكشن كـ dict."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    raw = response.content[0].text
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"الرد مش JSON: {raw}")
    return json.loads(match.group(0))


def run_action(page, action):
    """بينفذ الأكشن على المتصفح."""
    kind = action.get("action")

    if kind == "goto":
        page.goto(action["url"], timeout=30000)
    elif kind == "click":
        page.locator(f'[data-ai-id="{action["id"]}"]').first.click(timeout=10000)
    elif kind == "type":
        locator = page.locator(f'[data-ai-id="{action["id"]}"]').first
        locator.fill(action["text"], timeout=10000)
        if action.get("enter"):
            locator.press("Enter")
    elif kind == "press":
        page.keyboard.press(action["key"])
    elif kind == "scroll":
        page.mouse.wheel(0, 600)
    else:
        raise ValueError(f"أكشن غير معروف: {kind}")

    page.wait_for_timeout(1500)


def run_agent(task, start_url="https://www.google.com"):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # headless=False عشان تشوف المتصفح بيشتغل
        page = browser.new_page()
        page.goto(start_url)

        messages = []
        try:
            for step in range(1, MAX_STEPS + 1):
                print(f"\n--- خطوة {step} ---")
                state = describe_page(page, task)
                messages.append({"role": "user", "content": state})

                action = ask_model(messages)
                messages.append({"role": "assistant", "content": json.dumps(action, ensure_ascii=False)})
                print("الأكشن:", action)

                if action.get("action") == "done":
                    print("\n✅ النتيجة:")
                    print(action.get("answer", ""))
                    return action.get("answer", "")

                try:
                    run_action(page, action)
                except Exception as err:
                    # بنبلغ الموديل بالخطأ عشان يصلّح في الخطوة الجاية
                    messages.append({"role": "user", "content": f"الأكشن فشل: {err}. جرب حاجة تانية."})
                    print("⚠️ فشل الأكشن:", err)

            print("\nوصلنا لأقصى عدد خطوات من غير ما المهمة تخلص.")
            return None
        finally:
            browser.close()


if __name__ == "__main__":
    user_task = input("اكتب المهمة اللي عايز البرنامج ينفذها: ").strip()
    if user_task:
        run_agent(user_task)
