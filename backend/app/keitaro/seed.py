"""A FakeKeitaro with demo data, for KEITARO_FAKE=1 (local demos and the e2e suite)."""

import httpx

from app.config import Settings
from app.keitaro.fake import FakeKeitaro

_API = "https://fake.invalid/admin_api/v1"


def _post(fake: FakeKeitaro, path: str, body: dict) -> dict:
    return fake.handle(httpx.Request("POST", f"{_API}{path}", json=body)).json()


def with_fake_defaults(settings: Settings) -> Settings:
    """Blank .env defaults get the names the fake tracker is seeded with."""
    return settings.model_copy(update={
        "keitaro_default_domain": settings.keitaro_default_domain or "track.example",
        "keitaro_default_group": settings.keitaro_default_group or "Team",
        "keitaro_default_source": settings.keitaro_default_source or "Source",
    })


def fake_tracker(settings: Settings) -> FakeKeitaro:
    """The fake saved at KEITARO_FAKE_STATE when that file exists; otherwise a fresh seed,
    saved there from the start when the setting is given."""
    path = settings.keitaro_fake_state
    if path is not None and path.exists():
        return FakeKeitaro.load(path)
    fake = seeded_fake(settings)
    fake.state_file = path
    fake.save()
    return fake


def seeded_fake(settings: Settings) -> FakeKeitaro:
    """`settings` must already carry default names (see with_fake_defaults)."""
    fake = FakeKeitaro()
    fake.domains = [{"id": 1, "name": settings.keitaro_default_domain}]
    fake.groups = [{"id": 2, "name": settings.keitaro_default_group, "type": "campaigns"}]
    fake.sources = [{"id": 3, "name": settings.keitaro_default_source}]
    for offer_id, name in [(3749, "Flexacil PE"), (3717, "Oxys BE"), (11111, "Joint Rx RO"),
                           (11112, "Oxys [BEAUTY-CL-BE]"), (4242, "Cardio Fresh CZ")]:
        fake.add_offer(offer_id, name)
    fake.add_offer(500, "Someone else's offer", readable=False)
    campaign = _post(fake, "/campaigns", {"name": "Demo campaign", "alias": "demo1234",
                                          "domain_id": 1, "group_id": 2,
                                          "traffic_source_id": 3, "type": "position",
                                          "cost_type": "CPC"})
    _post(fake, "/streams", {"campaign_id": campaign["id"], "name": "Flow 1", "position": 1,
                             "type": "forced", "schema": "redirect", "action_type": "http",
                             "action_payload": "https://google.com",
                             "filters": [{"name": "country", "mode": "accept",
                                          "payload": ["AU"]}]})
    _post(fake, "/streams", {"campaign_id": campaign["id"], "name": "Flow 2", "position": 2,
                             "type": "regular", "schema": "landings", "action_type": "http",
                             "offers": [{"offer_id": 3749, "share": 34, "state": "active"},
                                        {"offer_id": 3717, "share": 33, "state": "active"},
                                        {"offer_id": 11111, "share": 33, "state": "active"}]})
    fake.requests.clear()
    return fake
