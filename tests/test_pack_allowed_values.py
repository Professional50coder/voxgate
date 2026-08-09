"""Every constrained field must be able to say what it allows.

A silent `None` from `allowed_values` does not read as "this lookup failed", it
reads as "this field is free text" — and free text takes the transcript
verbatim. So a naming slip downgrades a constrained compliance field to an
unvalidated one, quietly, with nothing failing.

That is not hypothetical. The hand-written `kyc-uae` pack named its constants
`VALID_SOF`, `VALID_PRODUCTS` and `VALID_RESIDENCY` while the contract is
`VALID_<FIELD_NAME>`, so every field in the flagship pack reported unconstrained.
Two consequences, neither of which failed anything:

  * `GroqExtractor` requires `allowed` and returns early without it, so the LLM
    extraction that makes spoken answers work was never running for this pack.
  * `KeywordExtractor` with no allowed values passes the transcript straight
    through, so "I get paid a monthly salary" was stored where `salary` belonged
    and the schema validator then rejected it — presenting as a re-ask loop
    rather than as the configuration error it was.

The invariant is stated as reachability rather than inferred from validator
behaviour, because inference is exactly what got this wrong the first time: a
`min_words` text validator and a date validator also reject an arbitrary string,
so "rejects nonsense" does not mean "is an enum". A `VALID_*` set that no field
can reach, on the other hand, is unambiguous — it is a constraint the extractor
will never see.
"""

import re
import sys
from pathlib import Path

import pytest

from voxgate.ml.extract import allowed_values
from voxgate.packs.loader import load_packs

PACKS = load_packs(Path(__file__).resolve().parents[1] / "packs")


def declared_value_sets(pack) -> dict[str, set]:
    """Module-level `VALID_*` sets in a pack's schema module."""
    module = sys.modules.get(pack.schema_model.__module__)
    if module is None:
        return {}
    return {
        name: value
        for name, value in vars(module).items()
        if name.startswith("VALID_") and isinstance(value, (set, frozenset))
    }


def reachable_value_sets(pack) -> dict[str, list[str]]:
    """What `allowed_values` can actually produce, per field."""
    return {
        name: found
        for name in pack.schema_model.model_fields
        if (found := allowed_values(pack.schema_model, name))
    }


@pytest.mark.parametrize("pack_id", sorted(PACKS))
def test_no_value_set_is_orphaned(pack_id):
    """The exact shape of the kyc-uae bug.

    A `VALID_*` set the extractor cannot reach is a field that has quietly
    become free text while still rejecting free text at validation time — which
    presents to an applicant as a question that can never be answered.
    """
    pack = PACKS[pack_id]
    declared = declared_value_sets(pack)
    reachable = {frozenset(v) for v in reachable_value_sets(pack).values()}

    orphaned = [
        name for name, values in declared.items()
        if frozenset(values) not in reachable
    ]
    assert not orphaned, (
        f"{pack_id}: {orphaned} declared but unreachable. The contract is a "
        f"module-level VALID_<FIELD_NAME> set; without the matching name the "
        f"field silently degrades to free text for the extractor while still "
        f"rejecting free text at validation."
    )


@pytest.mark.parametrize("pack_id", sorted(PACKS))
def test_every_advertised_value_actually_validates(pack_id):
    """The other direction: a field must not advertise a value its own schema
    rejects, or the extractor will confidently produce something unusable."""
    pack = PACKS[pack_id]
    for name, values in reachable_value_sets(pack).items():
        validator = pack.schema_model.model_fields[name]
        del validator
        for value in values:
            try:
                pack.schema_model.__pydantic_validator__.validate_assignment(
                    pack.schema_model.model_construct(), name, value
                )
            except Exception as exc:                       # noqa: BLE001
                pytest.fail(f"{pack_id}.{name} advertises {value!r}: {exc}")


@pytest.mark.parametrize("pack_id", sorted(PACKS))
def test_the_value_set_naming_convention_holds(pack_id):
    """Named so the failure explains itself.

    `emit.py` derives the name for generated packs, so only hand-written ones
    can break this — and kyc-uae, the flagship, is hand-written.
    """
    pack = PACKS[pack_id]
    fields = {f.upper() for f in pack.schema_model.model_fields}
    for name in declared_value_sets(pack):
        suffix = re.sub(r"^VALID_", "", name)
        assert suffix in fields, (
            f"{pack_id}: {name} does not match any field. Expected one of "
            f"{sorted('VALID_' + f for f in fields)}."
        )


def test_kyc_uae_specifically_exposes_its_enums():
    """The pack the regression was found in, named so a rename is loud."""
    pack = PACKS["kyc-uae"]
    assert allowed_values(pack.schema_model, "residency_status") == [
        "non_resident", "uae_resident",
    ]
    assert "salary" in allowed_values(pack.schema_model, "source_of_funds")
    assert "spot_trading" in allowed_values(pack.schema_model, "product")
