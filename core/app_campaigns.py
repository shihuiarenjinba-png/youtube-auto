"""Multi-source, URL-grounded application Campaign datasets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .advertising_rag import GroundedExtractor, PublicHttpsFetcher, RagHold, unique, validate_public_https


class CampaignHold(RagHold):
    pass


def load_campaign(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CampaignHold("HOLD_CAMPAIGN_DATASET_NOT_OBJECT")
    validate_campaign(value)
    return value


def validate_campaign(campaign: dict[str, Any]) -> None:
    for name in ("campaign_id", "app_id", "product_name", "market", "language", "official_url"):
        if not str(campaign.get(name) or "").strip():
            raise CampaignHold(f"HOLD_CAMPAIGN_FIELD_MISSING:{name}")
    market = str(campaign["market"]).upper()
    language = str(campaign["language"]).lower()
    if (market, language) not in {("JP", "ja"), ("US", "en")}:
        raise CampaignHold("HOLD_CAMPAIGN_MARKET_LANGUAGE_MISMATCH")
    if campaign.get("status") not in {"DRAFT", "ACTIVE", "HOLD"}:
        raise CampaignHold("HOLD_CAMPAIGN_STATUS_INVALID")
    source_urls = campaign.get("source_urls")
    if not isinstance(source_urls, list) or not source_urls:
        raise CampaignHold("HOLD_CAMPAIGN_SOURCE_URLS_MISSING")
    if len(source_urls) != len(set(source_urls)):
        raise CampaignHold("HOLD_CAMPAIGN_SOURCE_URL_DUPLICATE")
    for url in [campaign["official_url"], *source_urls]:
        validate_public_https(str(url))
    store_url = str(campaign.get("store_url") or "")
    if store_url:
        validate_public_https(store_url)
    cta_url = str(campaign.get("cta_url") or "")
    if cta_url:
        validate_public_https(cta_url)
        approved_ctas = {str(campaign["official_url"]), *[str(x) for x in source_urls]}
        if store_url:
            approved_ctas.add(store_url)
        if cta_url not in approved_ctas:
            raise CampaignHold("HOLD_CAMPAIGN_CTA_NOT_AN_APPROVED_SOURCE")
    for item in campaign.get("local_evidence") or []:
        if len(str(item.get("sha256") or "")) != 64 or not item.get("snippets"):
            raise CampaignHold("HOLD_LOCAL_EVIDENCE_INVALID")


def _local_snippets(campaign: dict[str, Any]) -> list[str]:
    return unique(
        [
            str(snippet)
            for item in campaign.get("local_evidence") or []
            for snippet in item.get("snippets") or []
        ],
        100,
    )


def build_grounded_dataset(
    campaign: dict[str, Any],
    *,
    fetcher: PublicHttpsFetcher | None = None,
) -> dict[str, Any]:
    validate_campaign(campaign)
    fetcher = fetcher or PublicHttpsFetcher()
    source_records: list[dict[str, Any]] = []
    remote_evidence: list[str] = []
    remote_features: list[str] = []
    for url in campaign["source_urls"]:
        final_url, body, html = fetcher.fetch(str(url))
        facts = GroundedExtractor().extract(
            campaign_id=str(campaign["campaign_id"]),
            requested_url=str(url),
            final_url=final_url,
            body=body,
            html=html,
        )
        source_records.append({
            "source_url": str(url),
            "canonical_url": facts.canonical_url,
            "source_sha256": facts.generated_from_source_hash,
            "evidence_snippets": facts.evidence_snippets,
        })
        remote_evidence.extend(facts.evidence_snippets)
        remote_features.extend(facts.features)

    local_evidence = _local_snippets(campaign)
    evidence = unique([*remote_evidence, *local_evidence], 120)
    corpus = "\n".join(evidence).casefold()
    product_name = str(campaign["product_name"])
    if product_name.casefold() not in corpus:
        raise CampaignHold("HOLD_CAMPAIGN_PRODUCT_NAME_NOT_GROUNDED")

    configured_facts = [
        *[str(x) for x in campaign.get("features") or []],
        *[str(x) for x in campaign.get("benefits") or []],
        *[str(x) for x in campaign.get("use_cases") or []],
        *[str(x) for x in campaign.get("system_requirements") or []],
    ]
    unsupported = [fact for fact in configured_facts if fact.casefold() not in corpus]
    if unsupported:
        raise CampaignHold("HOLD_CAMPAIGN_FACT_NOT_IN_EVIDENCE")

    source_hashes = [record["source_sha256"] for record in source_records]
    local_hashes = [str(item["sha256"]) for item in campaign.get("local_evidence") or []]
    evidence_hash = hashlib.sha256(
        json.dumps(evidence, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    aggregate_hash = hashlib.sha256("|".join([*source_hashes, *local_hashes]).encode("ascii")).hexdigest()
    result = dict(campaign)
    result.update({
        "source_records": source_records,
        "source_hashes": source_hashes,
        "generated_from_source_hash": aggregate_hash,
        "evidence_hash": evidence_hash,
        "evidence": evidence,
        "remote_features": unique(remote_features, 20),
        "grounding_status": "PASS",
        "posting_eligible": campaign.get("status") == "ACTIVE" and not campaign.get("hold_reasons"),
    })
    return result


def _build_ad_narration(
    product: str,
    description: str,
    features: list[str],
    use_cases: list[str],
    compatibility_notice: str,
    local_ai_notice: str,
) -> list[str]:
    """Create a short spoken summary; complete details remain in the caption/cards."""
    # Use the opening product-value sentence for speech; the full description remains
    # in the caption so narration stays comfortably within a short-form video.
    spoken_description = str(description or "").strip().split("。", 1)[0].strip()
    if spoken_description and not spoken_description.endswith(("。", "！", "？")):
        spoken_description += "。"
    lines = [f"{product}。", spoken_description]
    if features:
        lines.append("主な機能の一つは、" + features[0] + "です。")
    ai_independence = next((value for value in use_cases if "AIなし" in value), "")
    if ai_independence:
        lines.append("基本機能はAIなしでも利用できます。")
    elif use_cases:
        lines.append(use_cases[0])
    if local_ai_notice and "Ollama" not in description and not any("Ollama" in value for value in use_cases):
        lines.append(local_ai_notice)
    lines.append("詳しくは概要欄をご覧ください。")
    return [line for line in lines if line and line.strip()]


def generate_app_ad_content(dataset: dict[str, Any]) -> dict[str, Any]:
    if dataset.get("grounding_status") != "PASS":
        raise CampaignHold("HOLD_CAMPAIGN_GROUNDING_NOT_PASSED")
    features = [str(x) for x in dataset.get("features") or []]
    if len(features) < 2:
        raise CampaignHold("HOLD_INSUFFICIENT_SOURCE_EVIDENCE")
    product = str(dataset["product_name"])
    description = str(dataset.get("description") or "")
    cta_url = str(dataset.get("cta_url") or "")
    availability_notice = ""
    if dataset.get("limited_availability"):
        availability_notice = str(
            dataset.get("availability_notice_ja" if dataset.get("language") == "ja" else "availability_notice_en")
            or "提供数に上限があります。"
        ).strip()

    disclosure_statement = (
        "広告｜自社製品の紹介"
        if str(dataset.get("language") or "").lower() == "ja"
        else "Ad | Promotional content"
    )
    disclosure_label = "広告" if str(dataset.get("language") or "").lower() == "ja" else "Ad"
    requirements = [
        str(value).strip()
        for value in dataset.get("system_requirements") or []
        if str(value).strip()
    ]
    compatibility_notice = (
        "対応環境（Windows PC）：" + "、".join(requirements)
        if requirements else ""
    )
    optional_ai_feature = next(
        (feature for feature in features if "Ollama" in feature),
        "",
    )
    local_ai_notice = (
        f"AI補助機能：{optional_ai_feature}"
        if optional_ai_feature else ""
    )
    ai_independence_notice = next(
        (str(value) for value in dataset.get("use_cases") or [] if "AIなし" in str(value)),
        "",
    )
    store_link_notice = (
        f"入手先：Microsoft Storeで「{product}」を検索（Windows PC向け）"
        if cta_url and "apps.microsoft.com/search" in cta_url
        else "入手先"
    )
    video_end_card_lines = []
    if requirements:
        video_end_card_lines.append("対応：Windows 10／11（x64）")
    if optional_ai_feature:
        video_end_card_lines.append("任意のローカルOllama AI補助")
    if cta_url:
        video_end_card_lines.append(f"Microsoft Storeで「{product}」を検索")
    video_end_card_text = "\n".join(video_end_card_lines)

    use_cases = [str(value).strip() for value in dataset.get("use_cases") or [] if str(value).strip()]
    benefits = [str(value).strip() for value in dataset.get("benefits") or [] if str(value).strip()]
    caption_lines = [disclosure_statement, description]
    if benefits:
        caption_lines.extend(["\nこのアプリでできること", *[f"・{value}" for value in benefits]])
    if features:
        caption_lines.extend(["\n主な機能", *[f"・{value}" for value in features]])
    if use_cases:
        caption_lines.extend(["\nこんな場面に", *[f"・{value}" for value in use_cases]])
    for notice in (
        compatibility_notice,
        local_ai_notice,
        ai_independence_notice,
    ):
        if notice:
            caption_lines.append(notice)
    if availability_notice:
        caption_lines.append(availability_notice)
    if cta_url:
        caption_lines.append(f"{store_link_notice}\n{cta_url}")

    video_script = _build_ad_narration(
        product,
        description,
        features,
        use_cases,
        compatibility_notice,
        local_ai_notice,
    )

    return {
        "disclosure_statement": disclosure_statement,
        "disclosure_label": disclosure_label,
        "campaign_id": dataset["campaign_id"],
        "app_id": dataset["app_id"],
        "market": dataset["market"],
        "language": dataset["language"],
        "source_urls": dataset["source_urls"],
        "source_hashes": dataset["source_hashes"],
        "generated_from_source_hash": dataset["generated_from_source_hash"],
        "evidence_hash": dataset["evidence_hash"],
        "hook": f"{product} — {features[0]}",
        "summary": description,
        "key_features": features[:3],
        "video_script": video_script,
        "narration_text": "\\n".join(video_script),
        "compatibility_notice": compatibility_notice,
        "local_ai_notice": local_ai_notice,
        "ai_independence_notice": ai_independence_notice,
        "store_link_notice": store_link_notice,
        "video_end_card_text": video_end_card_text,
        "caption": "\n".join(caption_lines),
        "caption_has_cta_url": bool(cta_url and cta_url in "\n".join(caption_lines)),
        "limited_availability": bool(dataset.get("limited_availability")),
        "availability_notice": availability_notice,
        "hashtags": ["#PR", "#Windows", "#アプリ"],
        "cta_url": cta_url,
        "posting_eligible": bool(dataset["posting_eligible"]),
        "hold_reasons": list(dataset.get("hold_reasons") or []),
    }
