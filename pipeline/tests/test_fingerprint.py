"""Tests for structural fingerprinting logic."""

from drift_semantic.fingerprint import (
    _compute_idf,
    _wildcard_custom_tags,
    behavior_flags,
    data_access_pattern,
    hook_profile,
    import_constellation,
    jsx_hash,
)


class TestJsxHash:
    def test_no_jsx(self):
        result = jsx_hash({"id": "u1"})
        assert result == {"exact": None, "fuzzy": None}

    def test_same_tree_same_hash(self):
        tree = {"tag": "div", "children": [{"tag": "span", "children": []}]}
        a = jsx_hash({"jsxTree": tree})
        b = jsx_hash({"jsxTree": tree})
        assert a["exact"] == b["exact"]
        assert a["fuzzy"] == b["fuzzy"]

    def test_different_tree_different_hash(self):
        t1 = {"tag": "div", "children": []}
        t2 = {"tag": "span", "children": []}
        a = jsx_hash({"jsxTree": t1})
        b = jsx_hash({"jsxTree": t2})
        assert a["exact"] != b["exact"]

    def test_fuzzy_ignores_custom_tags(self):
        # PascalCase tags get wildcarded to <C>
        t1 = {"tag": "div", "children": [{"tag": "MyButton", "children": []}]}
        t2 = {"tag": "div", "children": [{"tag": "YourButton", "children": []}]}
        a = jsx_hash({"jsxTree": t1})
        b = jsx_hash({"jsxTree": t2})
        assert a["exact"] != b["exact"]  # exact differs
        assert a["fuzzy"] == b["fuzzy"]  # fuzzy same

    def test_fuzzy_preserves_html_tags(self):
        # Lowercase tags are NOT wildcarded
        t1 = {"tag": "div", "children": [{"tag": "span", "children": []}]}
        t2 = {"tag": "div", "children": [{"tag": "p", "children": []}]}
        a = jsx_hash({"jsxTree": t1})
        b = jsx_hash({"jsxTree": t2})
        assert a["fuzzy"] != b["fuzzy"]


class TestWildcardCustomTags:
    def test_pascal_case_replaced(self):
        tree = {"tag": "MyComponent", "children": []}
        result = _wildcard_custom_tags(tree)
        assert result["tag"] == "<C>"

    def test_html_preserved(self):
        tree = {"tag": "div", "children": []}
        result = _wildcard_custom_tags(tree)
        assert result["tag"] == "div"

    def test_nested(self):
        tree = {
            "tag": "div",
            "children": [{"tag": "Card", "children": [{"tag": "span", "children": []}]}],
        }
        result = _wildcard_custom_tags(tree)
        assert result["tag"] == "div"
        assert result["children"][0]["tag"] == "<C>"
        assert result["children"][0]["children"][0]["tag"] == "span"

    def test_none(self):
        assert _wildcard_custom_tags(None) is None

    def test_single_letter_not_matched(self):
        # Single uppercase letter doesn't match PascalCase regex (needs 2+ chars)
        tree = {"tag": "A", "children": []}
        result = _wildcard_custom_tags(tree)
        assert result["tag"] == "A"


class TestHookProfile:
    def test_empty(self):
        assert hook_profile({}) == [0] * 10

    def test_dict_format(self):
        unit = {"hookCalls": [{"name": "useState", "count": 3}, {"name": "useEffect", "count": 1}]}
        result = hook_profile(unit)
        assert result[0] == 3  # useState
        assert result[1] == 1  # useEffect
        assert result[2] == 0  # useCallback

    def test_string_format(self):
        unit = {"hookCalls": ["useState", "useState", "useRef"]}
        result = hook_profile(unit)
        assert result[0] == 2  # useState ×2
        assert result[4] == 1  # useRef

    def test_custom_hooks_ignored(self):
        unit = {"hookCalls": [{"name": "useMyCustomHook", "count": 5}]}
        result = hook_profile(unit)
        assert all(v == 0 for v in result)


class TestComputeIdf:
    def test_single_unit(self):
        units = [{"imports": [{"source": "react"}]}]
        idf = _compute_idf(units)
        # log(1/1) = 0
        assert idf["react"] == 0.0

    def test_rare_import_higher_idf(self):
        units = [
            {"imports": [{"source": "react"}, {"source": "lodash"}]},
            {"imports": [{"source": "react"}]},
        ]
        idf = _compute_idf(units)
        assert idf["lodash"] > idf["react"]

    def test_empty_units(self):
        assert _compute_idf([]) == {}


class TestImportConstellation:
    def test_weighting(self):
        idf = {"react": 0.5, "lodash": 2.0}
        unit = {"imports": [{"source": "react"}, {"source": "lodash"}]}
        vec = import_constellation(unit, idf)
        assert vec["react"] == 0.5
        assert vec["lodash"] == 2.0

    def test_unknown_source_ignored(self):
        idf = {"react": 1.0}
        unit = {"imports": [{"source": "unknown-pkg"}]}
        vec = import_constellation(unit, idf)
        assert len(vec) == 0


class TestBehaviorFlags:
    def test_all_false(self):
        assert behavior_flags({}) == [0] * 8

    def test_all_true(self):
        unit = {
            "isAsync": True,
            "hasErrorHandling": True,
            "hasLoadingState": True,
            "hasEmptyState": True,
            "hasRetryLogic": True,
            "rendersIteration": True,
            "rendersConditional": True,
            "sideEffects": True,
        }
        assert behavior_flags(unit) == [1] * 8

    def test_partial(self):
        unit = {"isAsync": True, "sideEffects": True}
        result = behavior_flags(unit)
        assert result[0] == 1  # isAsync
        assert result[7] == 1  # sideEffects
        assert sum(result) == 2


class TestDataAccessPattern:
    def test_empty(self):
        assert data_access_pattern({}) == {}

    def test_stores(self):
        unit = {"storeAccess": [{"name": "userStore"}, {"name": "appStore"}]}
        vec = data_access_pattern(unit)
        assert vec["store:userStore"] == 1.0
        assert vec["store:appStore"] == 1.0

    def test_data_sources(self):
        unit = {"dataSourceAccess": [{"name": "entities"}, {"name": "entities"}]}
        vec = data_access_pattern(unit)
        assert vec["ds:entities"] == 2.0

    def test_string_format(self):
        unit = {"storeAccess": ["myStore"]}
        vec = data_access_pattern(unit)
        assert vec["store:myStore"] == 1.0
