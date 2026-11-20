"""Opt-in contract checks against the real tracker: `uv run pytest -m live`.

They prove FakeKeitaro still matches Keitaro. They create ONE throwaway campaign with the
defaults from .env, work only inside it, and archive it at the end. They never call any
clean_archive endpoint and never read /campaigns/deleted (slow).
"""

import secrets

import pytest

from app.config import get_settings
from app.domain.flow import OfferLink
from app.keitaro.client import KeitaroClient, KeitaroError

pytestmark = pytest.mark.live


@pytest.fixture
async def kt():
    settings = get_settings()
    if not settings.keitaro_api_key.get_secret_value():
        pytest.skip("KEITARO_API_KEY is not set")
    client = KeitaroClient(settings.keitaro_base_url, settings.keitaro_api_key.get_secret_value())
    yield client
    await client.aclose()


async def _defaults(kt: KeitaroClient) -> dict[str, int]:
    s = get_settings()
    domains = {d.name: d.id for d in await kt.list_domains()}
    groups = {g.name: g.id for g in await kt.list_campaign_groups()}
    sources = {t.name: t.id for t in await kt.list_traffic_sources()}
    return {"domain_id": domains[s.keitaro_default_domain],
            "group_id": groups[s.keitaro_default_group],
            "traffic_source_id": sources[s.keitaro_default_source]}


async def test_fake_matches_the_real_tracker(kt):
    offers = await kt.list_offers()
    assert offers, "the key must see at least one offer"
    offer_id = offers[0].id
    await kt.list_deleted_offer_ids()  # parses

    campaign = await kt.create_campaign(name=f"kce-contract-{secrets.token_hex(3)}",
                                        alias=secrets.token_urlsafe(8), **await _defaults(kt))
    try:
        await kt.create_redirect_stream(campaign.id, "Flow 1", 1, ["AU", "NZ"],
                                        "https://google.com")
        flow2 = await kt.create_offer_stream(campaign.id, "Flow 2", 2,
                                             [OfferLink(offer_id, 100, "active")])
        forced, regular = await kt.list_streams(campaign.id)
        assert (forced.type, forced.redirect_url, forced.countries) == (
            "forced", "https://google.com", ["AU", "NZ"])
        assert regular.links == [OfferLink(offer_id, 100, "active")]

        # Keitaro does not validate shares, and PUT returns exactly what we sent
        await kt.put_stream_offers(flow2.id, [OfferLink(offer_id, 60, "active")])
        assert (await kt.get_stream(flow2.id)).links == [OfferLink(offer_id, 60, "active")]

        # PUT with offers replaces the list; [] empties it
        await kt.put_stream_offers(flow2.id, [])
        assert (await kt.get_stream(flow2.id)).links == []
    finally:
        await kt.archive_campaign(campaign.id)
    with pytest.raises(KeitaroError) as err:
        await kt.get_campaign(campaign.id)
    assert err.value.status == 404
