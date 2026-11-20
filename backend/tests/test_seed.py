"""The demo tracker for KEITARO_FAKE=1 looks like what the app itself creates."""

from pydantic import SecretStr

from app.config import Settings
from app.domain.flow import OfferLink
from app.keitaro.client import KeitaroClient
from app.keitaro.seed import seeded_fake, with_fake_defaults


async def test_demo_campaign_has_the_flow_layout_the_app_creates():
    settings = with_fake_defaults(Settings(_env_file=None, keitaro_base_url="https://t.example",
                                           keitaro_api_key=SecretStr("")))
    fake = seeded_fake(settings)
    kt = KeitaroClient("https://t.example", "k" * 32, transport=fake.transport)
    demo = next(c for c in await kt.list_campaigns() if c.name == "Demo campaign")
    made = await kt.create_campaign(name="Made", alias="made1", domain_id=demo.domain_id,
                                    group_id=demo.group_id,
                                    traffic_source_id=demo.traffic_source_id)
    await kt.create_redirect_stream(made.id, "Flow 1", 1, ["AU"], "https://google.com")
    await kt.create_offer_stream(made.id, "Flow 2", 2, [OfferLink(3749, 100, "active")])

    def layout(cid):
        return [(s["name"], s["position"], s["type"], s["schema"]) for s in fake.flows_of(cid)]

    assert layout(demo.id) == layout(made.id)
    await kt.aclose()
