# Apero wo?

**Apero wo?** is an informational tool designed to help people at ETH Zurich find Aperos and free food happening around campus. It crawls event sources daily, detects which events offer free food, and displays them in a calendar UI.

## Architecture

```
Sources → Extraction → Food detection → Scoring → Dedup → data/events.json → Calendar UI
```

Python backend pipeline processes sources concurrently, outputs `data/events.json`. Node.js/Express frontend serves a vanilla JS calendar. GitHub Actions runs the pipeline daily.

## Disclaimer

This tool is for **informational purposes only**. Free food at events is strictly limited to individuals who are officially inscribed to these events.

For content removal requests or feedback, use the **Feedback** button on the site or email ocalvet@ethz.ch.
