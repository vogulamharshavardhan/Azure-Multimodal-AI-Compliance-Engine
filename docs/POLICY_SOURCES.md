# Regulatory sources and corpus setup

Source families used by the existing implementation:

- FTC, [Disclosures 101 for Social Media Influencers](https://www.ftc.gov/business-guidance/resources/disclosures-101-social-media-influencers), local filename `1001a-influencer-guide-508_1.pdf`.
- FTC, [Endorsement Guides — What People Are Asking](https://www.ftc.gov/business-guidance/resources/ftcs-endorsement-guides-what-people-are-asking), local snapshot `ftc-endorsement-guides-faq.md`.
- [Google Ads Help](https://support.google.com/google-ads/), local snapshot `google-ads-youtube-video-specs.md`.

Review snapshot accuracy, authoritative source versions and redistribution rights before copying documents into `backend/data/`. Keep that folder out of public Git until reviewed. Run `uv run python -m backend.scripts.index_documents` for a fresh dedicated index after configuration. The corpus hash reflects local source files, not independently verified remote index contents. `backend/policies/registry.draft.json` is not approved or enforced as exhaustive coverage. The current project does not establish Indian or worldwide regulatory compliance. These links document the existing corpus; they have not been independently re-reviewed for current legal accuracy in this documentation pass.
