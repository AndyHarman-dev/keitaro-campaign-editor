"""Typed Keitaro client, driven against FakeKeitaro (the verified API behaviour, vision §4)."""

import logging

import httpx
import pytest

from app.domain.flow import OfferLink
from app.keitaro.client import ForbiddenPath, KeitaroClient, KeitaroError
from app.keitaro.fake import FakeKeitaro

KEY = "s3cr3t-key-0123456789abcdef012345"


@pytest.fixture
def fake() -> FakeKeitaro:
    kt = FakeKeitaro()
    kt.add_offer(18813, "Visible offer")
    kt.add_offer(500, "Someone else's offer", readable=False)
    return kt


@pytest.fixture
async def kt(fake):
    client = KeitaroClient("https://tracker.example", KEY, transport=fake.transport)
    yield client
    await client.aclose()


async def _campaign_with_offer_flow(kt: KeitaroClient, *offers: OfferLink) -> int:
    campaign = await kt.create_campaign(name="c", alias="a1", domain_id=1, group_id=2,
                                        traffic_source_id=3)
    stream = await kt.create_offer_stream(campaign.id, "Flow 2", 2, list(offers))
    return stream.id


async def test_create_campaign_and_both_flows_round_trip(kt):
    campaign = await kt.create_campaign(name="Spring", alias="abc123", domain_id=1, group_id=2,
                                        traffic_source_id=3)
    await kt.create_redirect_stream(campaign.id, "Flow 1", 1, ["AU", "NZ"], "https://google.com")
    await kt.create_offer_stream(campaign.id, "Flow 2", 2, [OfferLink(18813, 100, "active")])

    streams = await kt.list_streams(campaign.id)
    forced, offers = streams
    assert (forced.name, forced.type, forced.schema_, forced.redirect_url) == (
        "Flow 1", "forced", "redirect", "https://google.com")
    assert forced.countries == ["AU", "NZ"]
    assert (offers.type, offers.schema_, offers.links) == (
        "regular", "landings", [OfferLink(18813, 100, "active")])
    assert (await kt.get_campaign(campaign.id)).name == "Spring"


async def test_redirect_url_is_read_from_action_options_too(kt, fake):
    campaign = await kt.create_campaign(name="c", alias="a", domain_id=1, group_id=2,
                                        traffic_source_id=3)
    stream = await kt.create_redirect_stream(campaign.id, "Flow 1", 1, ["AU"], "https://g.co")
    fake.streams[stream.id]["action_payload"] = None
    fake.streams[stream.id]["action_options"] = {"url": "https://g.co"}
    assert (await kt.get_stream(stream.id)).redirect_url == "https://g.co"


async def test_put_offers_replaces_the_whole_list(kt):
    sid = await _campaign_with_offer_flow(kt, OfferLink(18813, 50, "active"),
                                          OfferLink(500, 50, "disabled"))
    await kt.put_stream_offers(sid, [OfferLink(500, 100, "disabled")])
    assert (await kt.get_stream(sid)).links == [OfferLink(500, 100, "disabled")]


async def test_re_added_offer_gets_a_new_link_id(kt, fake):
    sid = await _campaign_with_offer_flow(kt, OfferLink(18813, 100, "active"))
    first = fake.streams[sid]["offers"][0]["id"]
    await kt.put_stream_offers(sid, [OfferLink(18813, 100, "active")])
    assert fake.streams[sid]["offers"][0]["id"] == first
    await kt.put_stream_offers(sid, [OfferLink(500, 100, "active")])
    await kt.put_stream_offers(sid, [OfferLink(18813, 100, "active")])
    assert fake.streams[sid]["offers"][0]["id"] != first


async def test_archived_campaign_is_gone_from_get_and_list(kt):
    campaign = await kt.create_campaign(name="c", alias="a", domain_id=1, group_id=2,
                                        traffic_source_id=3)
    await kt.archive_campaign(campaign.id)
    with pytest.raises(KeitaroError) as err:
        await kt.get_campaign(campaign.id)
    assert err.value.status == 404
    assert campaign.id not in [c.id for c in await kt.list_campaigns()]


async def test_offers_lists_only_what_the_key_can_read(kt, fake):
    fake.add_offer(77, "Gone offer")
    fake.archive_offer(77)
    assert [o.id for o in await kt.list_offers()] == [18813]
    assert await kt.list_deleted_offer_ids() == {77}


async def test_lookups(kt, fake):
    fake.domains = [{"id": 1, "name": "track.example"}]
    fake.groups = [{"id": 2, "name": "Team", "type": "campaigns"},
                   {"id": 9, "name": "Offers", "type": "offers"}]
    fake.sources = [{"id": 3, "name": "Source"}]
    assert [(d.id, d.name) for d in await kt.list_domains()] == [(1, "track.example")]
    assert [(g.id, g.name) for g in await kt.list_campaign_groups()] == [(2, "Team")]
    assert [(s.id, s.name) for s in await kt.list_traffic_sources()] == [(3, "Source")]


async def test_errors_carry_status_and_keitaros_message(kt, fake):
    fake.fail_next("POST", "/campaigns", 400, "Alias is already taken")
    with pytest.raises(KeitaroError) as err:
        await kt.create_campaign(name="c", alias="a", domain_id=1, group_id=2,
                                 traffic_source_id=3)
    assert (err.value.status, err.value.message) == (400, "Alias is already taken")


async def test_non_json_error_body_still_maps_to_keitaro_error(fake):
    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>Bad gateway</html>")

    client = KeitaroClient("https://tracker.example", KEY, transport=httpx.MockTransport(broken))
    with pytest.raises(KeitaroError) as err:
        await client.list_campaigns()
    assert (err.value.status, err.value.message) == (502, "<html>Bad gateway</html>")


async def test_unreachable_tracker_maps_to_keitaro_error():
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = KeitaroClient("https://tracker.example", KEY, transport=httpx.MockTransport(down))
    with pytest.raises(KeitaroError) as err:
        await client.list_campaigns()
    assert err.value.status == 0


@pytest.mark.parametrize("path", ["/campaigns/clean_archive", "/offers/clean_archive",
                                  "/landing_pages/clean_archive/", "/x/Clean_Archive"])
async def test_clean_archive_is_refused_before_any_request(fake, path):
    client = KeitaroClient("https://tracker.example", KEY, transport=fake.transport)
    with pytest.raises(ForbiddenPath):
        await client._request("POST", path)
    assert fake.requests == []


async def test_api_key_never_appears_in_errors_or_logs(kt, fake, caplog):
    caplog.set_level(logging.DEBUG)
    fake.fail_next("GET", "/campaigns", 401, "Unauthorized")
    with pytest.raises(KeitaroError) as err:
        await kt.list_campaigns()
    assert KEY not in repr(err.value) + str(err.value)
    assert KEY not in caplog.text
    assert KEY not in repr(kt)


async def test_api_key_is_sent_in_the_api_key_header(kt, fake):
    await kt.list_campaigns()
    assert fake.requests[-1].headers["Api-Key"] == KEY
    assert str(fake.requests[-1].url).startswith("https://tracker.example/admin_api/v1/")


async def test_error_body_without_an_error_field_falls_back_to_the_raw_text():
    def odd(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "bad"})

    client = KeitaroClient("https://tracker.example", KEY, transport=httpx.MockTransport(odd))
    with pytest.raises(KeitaroError) as err:
        await client.list_campaigns()
    assert err.value.message == '{"message":"bad"}'


async def test_empty_action_payload_falls_back_to_action_options(kt, fake):
    campaign = await kt.create_campaign(name="c", alias="a", domain_id=1, group_id=2,
                                        traffic_source_id=3)
    stream = await kt.create_redirect_stream(campaign.id, "Flow 1", 1, ["AU"], "https://g.co")
    fake.streams[stream.id]["action_payload"] = ""
    fake.streams[stream.id]["action_options"] = {"url": "https://g.co"}
    assert (await kt.get_stream(stream.id)).redirect_url == "https://g.co"


@pytest.mark.parametrize("body", [{"name": "only name"}, {"alias": "only-alias"}])
async def test_fake_rejects_a_campaign_without_name_or_alias(kt, body):
    # mirrors the live tracker: create requires both
    with pytest.raises(KeitaroError) as err:
        await kt._request("POST", "/campaigns", json=body)
    assert err.value.status == 400


async def test_detached_offer_leaves_the_flow(kt, fake):
    sid = await _campaign_with_offer_flow(kt, OfferLink(18813, 50, "active"),
                                          OfferLink(500, 50, "active"))
    fake.detach_offer(sid, 18813)
    assert [link.offer_id for link in (await kt.get_stream(sid)).links] == [500]


async def test_campaigns_carry_group_and_domain_names_like_keitaro(kt, fake):
    fake.domains = [{"id": 1, "name": "track.example"}]
    fake.groups = [{"id": 2, "name": "Team", "type": "campaigns"}]
    campaign = await kt.create_campaign(name="c", alias="a", domain_id=1, group_id=2,
                                        traffic_source_id=3)
    listed = (await kt.list_campaigns())[0]
    assert (listed.group, listed.domain) == ("Team", "https://track.example/")
    assert (await kt.get_campaign(campaign.id)).group == "Team"
