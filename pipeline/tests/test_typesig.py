"""Tests for type signature normalization."""

from drift_semantic.typesig import _classify_type, normalize_type


class TestClassifyType:
    def test_void(self):
        c = _classify_type("void")
        assert c["has_void"] is True
        assert c["has_function"] is False

    def test_undefined(self):
        assert _classify_type("undefined")["has_void"] is True

    def test_never(self):
        assert _classify_type("never")["has_void"] is True

    def test_function_arrow(self):
        assert _classify_type("(x: number) => void")["has_function"] is True

    def test_function_keyword(self):
        assert _classify_type("Function")["has_function"] is True

    def test_callback(self):
        assert _classify_type("callback")["has_function"] is True

    def test_object_literal(self):
        assert _classify_type("{ name: string }")["has_object"] is True

    def test_record(self):
        assert _classify_type("Record<string, number>")["has_object"] is True

    def test_array_brackets(self):
        assert _classify_type("string[]")["has_array"] is True

    def test_array_generic(self):
        assert _classify_type("Array<number>")["has_array"] is True

    def test_plain_string(self):
        c = _classify_type("string")
        assert not any(c.values())


class TestNormalizeType:
    def test_basic(self):
        result = normalize_type([{"type": "string"}, {"type": "number"}], "void")
        assert result["canonical"] == "(string, number) => void"
        assert result["strict_hash"] is not None
        assert result["loose_hash"] is not None

    def test_no_params(self):
        result = normalize_type([], "boolean")
        assert result["canonical"] == "() => boolean"

    def test_strict_hash_differs_on_type(self):
        a = normalize_type([{"type": "string"}], "void")
        b = normalize_type([{"type": "number"}], "void")
        assert a["strict_hash"] != b["strict_hash"]

    def test_strict_hash_same_for_same_types(self):
        a = normalize_type([{"type": "string"}], "void")
        b = normalize_type([{"type": "string"}], "void")
        assert a["strict_hash"] == b["strict_hash"]

    def test_loose_hash_same_for_same_shape(self):
        # Both: arity=1, has_function_param=False, void return
        a = normalize_type([{"type": "string"}], "void")
        b = normalize_type([{"type": "number"}], "void")
        assert a["loose_hash"] == b["loose_hash"]

    def test_loose_hash_differs_on_arity(self):
        a = normalize_type([{"type": "string"}], "void")
        b = normalize_type([{"type": "string"}, {"type": "string"}], "void")
        assert a["loose_hash"] != b["loose_hash"]

    def test_loose_hash_differs_on_function_param(self):
        a = normalize_type([{"type": "string"}], "void")
        b = normalize_type([{"type": "(x: number) => void"}], "void")
        assert a["loose_hash"] != b["loose_hash"]

    def test_default_type_is_any(self):
        result = normalize_type([{}], "void")
        assert result["canonical"] == "(any) => void"
