"""Tests for CSS extraction and fingerprinting."""

from drift_semantic.css_extract import (
    _extract_class_names,
    _extract_prefix,
    _parse_declarations,
    _strip_comments,
    parse_css,
    _compute_file_aggregates,
)


class TestStripComments:
    def test_single_comment(self):
        assert _strip_comments("a /* comment */ b") == "a  b"

    def test_multiline_comment(self):
        css = "a {\n/* multi\nline\ncomment */\n  color: red;\n}"
        result = _strip_comments(css)
        assert "/*" not in result
        assert "color: red" in result

    def test_no_comments(self):
        assert _strip_comments("a { color: red; }") == "a { color: red; }"


class TestParseDeclarations:
    def test_simple(self):
        decls = _parse_declarations("color: red; font-size: 16px")
        assert len(decls) == 2
        assert decls[0] == {"name": "color", "value": "red"}
        assert decls[1] == {"name": "font-size", "value": "16px"}

    def test_empty(self):
        assert _parse_declarations("") == []
        assert _parse_declarations("   ") == []

    def test_no_colon(self):
        assert _parse_declarations("just-text") == []

    def test_value_with_colon(self):
        decls = _parse_declarations("background: url(http://example.com)")
        assert len(decls) == 1
        assert decls[0]["name"] == "background"
        assert "http://example.com" in decls[0]["value"]

    def test_lowercases_property(self):
        decls = _parse_declarations("Color: Red")
        assert decls[0]["name"] == "color"
        # Value is NOT lowercased
        assert decls[0]["value"] == "Red"


class TestExtractClassNames:
    def test_single_class(self):
        assert _extract_class_names(".btn") == ["btn"]

    def test_multiple_classes(self):
        assert _extract_class_names(".btn.btn-primary") == ["btn", "btn-primary"]

    def test_no_classes(self):
        assert _extract_class_names("div > p") == []

    def test_mixed_selector(self):
        assert _extract_class_names("div.container > .header") == ["container", "header"]

    def test_bem(self):
        assert _extract_class_names(".filter-panel__header--active") == ["filter-panel__header--active"]


class TestExtractPrefix:
    def test_bem_element(self):
        assert _extract_prefix("filter-panel__header") == "filter-panel"

    def test_bem_modifier(self):
        assert _extract_prefix("filter-panel--active") == "filter-panel"

    def test_hyphenated_three_parts(self):
        assert _extract_prefix("filter-panel-header") == "filter-panel"

    def test_simple_name(self):
        assert _extract_prefix("btn") == "btn"

    def test_two_parts(self):
        assert _extract_prefix("btn-primary") == "btn-primary"


class TestParseCss:
    def test_simple_rule(self):
        css = ".btn { color: red; font-size: 14px; }"
        rules = parse_css(css)
        assert len(rules) == 1
        assert rules[0]["selector"] == ".btn"
        assert rules[0]["classNames"] == ["btn"]
        assert len(rules[0]["properties"]) == 2
        assert rules[0]["propertyValueHash"]
        assert rules[0]["propertySetHash"]

    def test_multiple_rules(self):
        css = ".a { color: red; }\n.b { color: blue; }"
        rules = parse_css(css)
        assert len(rules) == 2
        assert rules[0]["selector"] == ".a"
        assert rules[1]["selector"] == ".b"

    def test_media_query(self):
        css = "@media (max-width: 768px) { .btn { display: none; } }"
        rules = parse_css(css)
        assert len(rules) == 1
        assert rules[0]["selector"] == ".btn"
        assert rules[0]["mediaQuery"] == "@media (max-width: 768px)"

    def test_skips_keyframes(self):
        css = "@keyframes spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }\n.spinner { animation: spin 1s; }"
        rules = parse_css(css)
        assert len(rules) == 1
        assert rules[0]["selector"] == ".spinner"

    def test_skips_font_face(self):
        css = "@font-face { font-family: 'Custom'; src: url('font.woff'); }\n.text { font-family: Custom; }"
        rules = parse_css(css)
        assert len(rules) == 1
        assert rules[0]["selector"] == ".text"

    def test_comment_stripping(self):
        css = "/* header styles */\n.header { /* main color */ color: blue; }"
        rules = parse_css(css)
        assert len(rules) == 1
        assert rules[0]["classNames"] == ["header"]

    def test_empty_rule(self):
        css = ".empty { }"
        rules = parse_css(css)
        assert len(rules) == 0

    def test_fingerprint_determinism(self):
        css = ".a { color: red; font-size: 14px; }"
        r1 = parse_css(css)
        r2 = parse_css(css)
        assert r1[0]["propertyValueHash"] == r2[0]["propertyValueHash"]
        assert r1[0]["propertySetHash"] == r2[0]["propertySetHash"]

    def test_different_values_same_property_set_hash(self):
        css_a = ".a { color: red; font-size: 14px; }"
        css_b = ".b { color: blue; font-size: 16px; }"
        ra = parse_css(css_a)
        rb = parse_css(css_b)
        # Same properties, different values: propertySetHash should match
        assert ra[0]["propertySetHash"] == rb[0]["propertySetHash"]
        # But propertyValueHash should differ
        assert ra[0]["propertyValueHash"] != rb[0]["propertyValueHash"]

    def test_line_range(self):
        css = "\n\n.btn {\n  color: red;\n}\n"
        rules = parse_css(css)
        assert len(rules) == 1
        # Line range should be somewhere around lines 3-5
        assert rules[0]["lineRange"][0] >= 1
        assert rules[0]["lineRange"][1] >= rules[0]["lineRange"][0]

    def test_custom_properties(self):
        css = ":root { --primary: #333; }\n.btn { color: var(--primary); background: var(--bg-color); }"
        rules = parse_css(css)
        assert len(rules) == 2


class TestComputeFileAggregates:
    def test_basic_aggregates(self):
        rules = [
            {
                "classNames": ["btn", "btn-primary"],
                "properties": [
                    {"name": "display", "value": "flex"},
                    {"name": "color", "value": "red"},
                    {"name": "padding", "value": "10px"},
                ],
            },
            {
                "classNames": ["btn-secondary"],
                "properties": [
                    {"name": "display", "value": "block"},
                    {"name": "font-size", "value": "14px"},
                ],
            },
        ]
        agg = _compute_file_aggregates(rules)

        assert "btn" in agg["selectorPrefixes"]
        assert agg["propertyFrequency"]["display"] == 2
        assert agg["propertyFrequency"]["color"] == 1
        # Category profile should have non-zero layout (display)
        assert agg["categoryProfile"][0] > 0  # layout

    def test_custom_properties(self):
        rules = [
            {
                "classNames": ["theme"],
                "properties": [
                    {"name": "--primary", "value": "#333"},
                    {"name": "color", "value": "var(--primary)"},
                    {"name": "background", "value": "var(--bg-color)"},
                ],
            },
        ]
        agg = _compute_file_aggregates(rules)
        assert "--primary" in agg["customPropertyDeclarations"]
        assert "--primary" in agg["customPropertyReferences"]
        assert "--bg-color" in agg["customPropertyReferences"]

    def test_empty_rules(self):
        agg = _compute_file_aggregates([])
        assert agg["selectorPrefixes"] == []
        assert agg["propertyFrequency"] == {}
        assert agg["categoryProfile"] == [0, 0, 0, 0, 0, 0, 0]
