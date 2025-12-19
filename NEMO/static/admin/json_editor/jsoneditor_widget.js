// Create a simple django theme based off the HTML one
JSONEditor.defaults.themes.django = class DjangoTheme extends JSONEditor.defaults.themes.html
{
    getButton(text, icon, title)
    {
        const el = super.getButton(text, icon, title);
        el.setAttribute("class", `button`);
        return el;
    }

    setGridColumnSize(el, size)
    {
        el.setAttribute("style", `width: ${(size / 12) * 100}%`);
    }
}

/* Initiate JSON editor in admin form */
document.addEventListener("DOMContentLoaded", () =>
{
    const editors = document.querySelectorAll(".json_schema_editor");
    for (const el of editors)
    {
        const textarea = el.querySelector("textarea");
        if (textarea && !textarea.id.includes("__prefix__"))
        {
            initEditor(el);
        }
    }
})

/* Initiate JSON editor in admin formset */
document.addEventListener("DOMContentLoaded", () =>
{
    django.jQuery(document).on("formset:added", (event) =>
    {
        const editors = event.target.querySelectorAll(".json_schema_editor");
        for (const el of editors)
        {
            initEditor(el);
        }
    })
})

let editorIndex = 0;

const initEditor = (el) =>
{
    const input = el.querySelector("textarea");
    const config = JSON.parse(el.dataset.editorConfig);

    let value;
    if (input.value && (value = JSON.parse(input.value)))
    {
        config.startval = value;
    }

    // Set a unique name so that form widgets get somewhat more unique names
    config.form_name_root = `jse${++editorIndex}`;

    const editor = new JSONEditor(el, config);
    editor.on("change", () =>
    {
        input.value = JSON.stringify(editor.getValue());
    })

    // The JSON is only updated on change events. This can cause edits to be lost
    // when directly triggering a save without first leaving the input element.
    // (e.g. when using ctrl-s in the django-content-editor)
    const dispatchChangeEventOnInput = debounce((e) =>
    {
        if (e.target.matches("input, textarea"))
        {
            e.target.dispatchEvent(new Event("change", {bubbles: true}));
        }
    }, 100)

    editor.element.addEventListener("input", dispatchChangeEventOnInput);
}

const debounce = (f, ms) =>
{
    let t;
    return (...a) =>
    {
        clearTimeout(t);
        t = setTimeout(() => f(...a), ms);
    }
}
