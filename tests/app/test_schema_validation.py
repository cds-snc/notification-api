from app.schema_validation import _sort_errors_by_priority


class TestSortErrorsByPriority:
    """Test the _sort_errors_by_priority function"""

    def test_sort_errors_by_priority_with_single_error(self):
        """Test sorting with a single error returns the same error"""
        errors = [{"error": "ValidationError", "message": "field1 is required", "validator": "required"}]

        result = _sort_errors_by_priority(errors)

        assert len(result) == 1
        assert result[0] == errors[0]

    def test_sort_errors_by_priority_with_required_first(self):
        """Test that required errors come first"""
        errors = [
            {"error": "ValidationError", "message": "Invalid format", "validator": "format"},
            {"error": "ValidationError", "message": "field1 is required", "validator": "required"},
            {"error": "ValidationError", "message": "Invalid type", "validator": "type"},
        ]

        result = _sort_errors_by_priority(errors)

        assert len(result) == 3
        assert result[0]["validator"] == "required"
        assert result[1]["validator"] == "format"
        assert result[2]["validator"] == "type"

    def test_sort_errors_by_priority_with_all_validator_types(self):
        """Test sorting with all defined validator types"""
        errors = [
            {"error": "ValidationError", "message": "Pattern mismatch", "validator": "pattern"},
            {"error": "ValidationError", "message": "Invalid enum value", "validator": "enum"},
            {"error": "ValidationError", "message": "Invalid type", "validator": "type"},
            {"error": "ValidationError", "message": "Invalid format", "validator": "format"},
            {"error": "ValidationError", "message": "field1 is required", "validator": "required"},
        ]

        result = _sort_errors_by_priority(errors)

        expected_order = ["required", "format", "type", "enum", "pattern"]
        actual_order = [error["validator"] for error in result]

        assert actual_order == expected_order

    def test_sort_errors_by_priority_with_unknown_validators(self):
        """Test that unknown validators are placed at the end"""
        errors = [
            {"error": "ValidationError", "message": "Unknown validation", "validator": "unknown_validator"},
            {"error": "ValidationError", "message": "field1 is required", "validator": "required"},
            {"error": "ValidationError", "message": "Another unknown", "validator": "custom_validator"},
        ]

        result = _sort_errors_by_priority(errors)

        assert len(result) == 3
        assert result[0]["validator"] == "required"
        # Unknown validators should be at the end, order among them doesn't matter
        unknown_validators = [result[1]["validator"], result[2]["validator"]]
        assert "unknown_validator" in unknown_validators
        assert "custom_validator" in unknown_validators

    def test_sort_errors_by_priority_with_missing_validator_key(self):
        """Test handling of errors without validator key"""
        errors = [
            {"error": "ValidationError", "message": "No validator key"},
            {"error": "ValidationError", "message": "field1 is required", "validator": "required"},
        ]

        result = _sort_errors_by_priority(errors)

        assert len(result) == 2
        assert result[0]["validator"] == "required"
        # Error without validator key should be treated as "unknown" and placed at end
        assert "validator" not in result[1] or result[1].get("validator") is None

    def test_sort_errors_by_priority_maintains_stability(self):
        """Test that errors with same priority maintain their relative order"""
        errors = [
            {"error": "ValidationError", "message": "First format error", "validator": "format"},
            {"error": "ValidationError", "message": "Second format error", "validator": "format"},
            {"error": "ValidationError", "message": "Third format error", "validator": "format"},
        ]

        result = _sort_errors_by_priority(errors)

        assert len(result) == 3
        # All should have same validator
        assert all(error["validator"] == "format" for error in result)
        # Order should be maintained (stable sort)
        assert result[0]["message"] == "First format error"
        assert result[1]["message"] == "Second format error"
        assert result[2]["message"] == "Third format error"

    def test_sort_errors_by_priority_with_empty_list(self):
        """Test sorting with empty error list"""
        errors = []

        result = _sort_errors_by_priority(errors)

        assert result == []

    def test_sort_errors_by_priority_complex_scenario(self):
        """Test a complex scenario with multiple error types mixed together"""
        errors = [
            {"error": "ValidationError", "message": "Unknown error 1", "validator": "mystery"},
            {"error": "ValidationError", "message": "Bad pattern", "validator": "pattern"},
            {"error": "ValidationError", "message": "Missing field", "validator": "required"},
            {"error": "ValidationError", "message": "Wrong type", "validator": "type"},
            {"error": "ValidationError", "message": "Bad enum", "validator": "enum"},
            {"error": "ValidationError", "message": "Bad format", "validator": "format"},
            {"error": "ValidationError", "message": "Another missing field", "validator": "required"},
            {"error": "ValidationError", "message": "Unknown error 2", "validator": "another_mystery"},
        ]

        result = _sort_errors_by_priority(errors)

        assert len(result) == 8

        # Check the order by priority
        validators = [error["validator"] for error in result]

        # Required errors should come first (2 of them)
        assert validators[0] == "required"
        assert validators[1] == "required"

        # Format should come next
        assert validators[2] == "format"

        # Type should come next
        assert validators[3] == "type"

        # Enum should come next
        assert validators[4] == "enum"

        # Pattern should come next
        assert validators[5] == "pattern"

        # Unknown validators should come last (2 of them)
        assert validators[6] in ["mystery", "another_mystery"]
        assert validators[7] in ["mystery", "another_mystery"]
        assert validators[6] != validators[7]  # Both should be present
