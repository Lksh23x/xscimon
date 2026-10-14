from pathlib import Path

from xscimon.repositories import AccountRepo, DomainRepo, KeywordRepo
from xscimon.services import SeedService

SEED_DIR = Path(__file__).resolve().parents[1] / "seed"


def _write_seed(tmp_path: Path) -> Path:
    (tmp_path / "skills").mkdir()
    (tmp_path / "accounts").mkdir()
    (tmp_path / "skills" / "bio.md").write_text("Focus on CRISPR.\n")
    (tmp_path / "accounts" / "bio.csv").write_text(
        "handle,display_name,description,credibility\n"
        "@lab_a,Lab A,,high\n"
        "lab_b,,,\n"
        ",,,\n"
    )
    (tmp_path / "seed.yaml").write_text(
        "domains:\n"
        "  - name: Bio\n"
        "    top_n: 5\n"
        "    skill: skills/bio.md\n"
        "    accounts: accounts/bio.csv\n"
        "keywords:\n"
        "  - name: Editing\n"
        "    query: CRISPR OR \"base editing\"\n"
        "    mode: preset\n"
    )
    return tmp_path


def test_seed_loads_domains_accounts_and_rules(session, tmp_path):
    summary = SeedService(session).load(_write_seed(tmp_path))
    assert summary == {"domains": [{"name": "Bio", "accounts": 2}], "keywords": 1}

    domain = DomainRepo(session).get_by_name("Bio")
    assert domain.top_n == 5 and domain.skill_md == "Focus on CRISPR."
    accounts = {a.handle: a for a in AccountRepo(session).get_for_domain(domain.id)}
    assert set(accounts) == {"lab_a", "lab_b"}
    assert accounts["lab_a"].credibility.value == "high"
    assert KeywordRepo(session).get_presets()[0].name == "Editing"


def test_seed_is_idempotent_and_applies_edits(session, tmp_path):
    seed_dir = _write_seed(tmp_path)
    SeedService(session).load(seed_dir)
    (seed_dir / "skills" / "bio.md").write_text("Focus on prime editing.\n")
    SeedService(session).load(seed_dir)

    assert len(DomainRepo(session).get_all()) == 1
    assert len(KeywordRepo(session).get_all()) == 1
    domain = DomainRepo(session).get_by_name("Bio")
    assert domain.skill_md == "Focus on prime editing."
    assert len(AccountRepo(session).get_for_domain(domain.id)) == 2


def test_bundled_seed_is_valid(session):
    summary = SeedService(session).load(SEED_DIR)
    assert summary["domains"] and all(d["accounts"] > 0 for d in summary["domains"])
    assert all(d.skill_md for d in DomainRepo(session).get_all())
