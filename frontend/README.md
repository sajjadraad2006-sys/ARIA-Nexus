# ARIA Nexus — Frontend (SPA)

A dependency-free, vanilla-JavaScript single-page app. There is **no build
step and zero iframes** — `nexus_app.html` is the single entry point and every
module renders into one shared DOM.

## Folder layout

```
frontend/
├── README.md
└── application/
    ├── nexus_app.html         # single entry point (the whole SPA shell)
    ├── UI_TEXTURE_NOTES.md     # design notes for the texture/visual system
    ├── css/
    │   ├── nexus.css           # core layout + design tokens
    │   ├── animations.css      # transitions / keyframes
    │   ├── textures.css        # background textures
    │   ├── polish.css          # visual polish + mobile-responsive rules
    │   ├── perf.css            # performance / reduced-motion tweaks
    │   ├── face.css            # assistant face view
    │   ├── call.css            # voice-call overlay
    │   ├── settings.css        # settings drawer
    │   ├── fonts.css           # @font-face declarations
    │   └── rtl.css             # right-to-left (Arabic) overrides
    └── js/
        ├── nexus.js            # app bootstrap + view router/shell
        ├── api.js              # REST client (uses window.location.origin)
        ├── i18n.js             # EN/AR strings + RTL switching
        ├── voice.js            # TTS voice manager (language -> voice matching)
        ├── mic.js              # microphone capture / streaming
        ├── wake.js             # wake-word UI glue
        ├── wakelistener.js     # local wake-word listener
        ├── settings.js         # settings drawer logic
        ├── icons.js            # inline SVG icon set
        ├── particles.js        # ambient background particles
        ├── pages/              # one module per feature view
        │   ├── chatbot.js      # chat
        │   ├── assistant.js    # assistant / agent view
        │   ├── face.js         # animated face
        │   ├── call.js         # hands-free voice call
        │   ├── iot.js          # IoT / smart-home control
        │   ├── knowledge.js    # RAG knowledge base
        │   ├── monitor.js      # system monitor
        │   ├── tts.js          # TTS studio
        │   └── exporter.js     # system exporter
        └── vendor/
            ├── nx-markdown.js  # tiny markdown renderer
            └── nx-sound.js     # sound-effects helper
```

## Serving

The frontend is served directly by the Flask backend (`backend/server.py`); open
the backend host in a browser. `api.js` derives the API base from
`window.location.origin`, so there are no hard-coded hosts or redirects.
