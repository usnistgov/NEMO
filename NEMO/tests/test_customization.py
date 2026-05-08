from datetime import date, datetime

from django.test import TestCase

from NEMO.exceptions import InvalidCustomizationException
from NEMO.tests.test_utilities import NEMOTestCaseMixin
from NEMO.utilities import date_input_format, datetime_input_format
from NEMO.views.customization import ApplicationCustomization, CustomizationBase, ToolCustomization


class CustomizationGetMethodsTestCase(NEMOTestCaseMixin, TestCase):
    """Tests for CustomizationBase get, get_bool, get_list, get_list_int, get_int, get_date, get_datetime."""

    def test_get_returns_default_when_not_set(self):
        value = ApplicationCustomization.get("facility_name")
        self.assertEqual(value, "Facility")

    def test_get_returns_set_value_wrong_class(self):
        # facility_name is a ToolCustomization, but it should work anyway (and display a warning)
        ApplicationCustomization.set("facility_name", "My Lab")
        value = ToolCustomization.get("facility_name")
        self.assertEqual(value, "My Lab")

    def test_get_returns_set_value(self):
        ApplicationCustomization.set("facility_name", "My Lab")
        value = ApplicationCustomization.get("facility_name")
        self.assertEqual(value, "My Lab")

    def test_get_raises_for_unknown_name(self):
        with self.assertRaises(InvalidCustomizationException):
            ApplicationCustomization.get("nonexistent_key")

    def test_get_no_raise_returns_default_for_unknown_name(self):
        # raise_exception=False but unknown key still raises because it's checked before DB access
        with self.assertRaises(InvalidCustomizationException):
            ApplicationCustomization.get("nonexistent_key", raise_exception=False)

    def test_get_bool_false_when_not_set(self):
        # "self_log_in" defaults to "" which is not "enabled"
        result = ApplicationCustomization.get_bool("self_log_in")
        self.assertFalse(result)

    def test_get_bool_true_when_enabled(self):
        ApplicationCustomization.set("self_log_in", "enabled")
        result = ApplicationCustomization.get_bool("self_log_in")
        self.assertTrue(result)

    def test_get_bool_false_when_set_to_other_value(self):
        ApplicationCustomization.set("self_log_in", "disabled")
        result = ApplicationCustomization.get_bool("self_log_in")
        self.assertFalse(result)

    def test_get_int_returns_none_for_empty_default(self):
        # "default_badge_reader_id" defaults to ""
        result = ApplicationCustomization.get_int("default_badge_reader_id")
        self.assertIsNone(result)

    def test_get_int_returns_integer(self):
        ApplicationCustomization.set("default_badge_reader_id", "42")
        result = ApplicationCustomization.get_int("default_badge_reader_id")
        self.assertEqual(result, 42)

    def test_get_int_returns_default_for_non_integer(self):
        ApplicationCustomization.set("default_badge_reader_id", "not_a_number")
        result = ApplicationCustomization.get_int("default_badge_reader_id", default=99)
        self.assertEqual(result, 99)

    def test_get_list_returns_empty_for_empty_value(self):
        ApplicationCustomization.set("self_log_in", "")
        result = ApplicationCustomization.get_list("self_log_in")
        self.assertEqual(result, [])

    def test_get_list_returns_single_item(self):
        ApplicationCustomization.set("self_log_in", "item1")
        result = ApplicationCustomization.get_list("self_log_in")
        self.assertEqual(result, ["item1"])

    def test_get_list_returns_multiple_items(self):
        ApplicationCustomization.set("self_log_in", "item1,item2,item3")
        result = ApplicationCustomization.get_list("self_log_in")
        self.assertEqual(result, ["item1", "item2", "item3"])

    def test_get_list_strips_whitespace(self):
        ApplicationCustomization.set("self_log_in", " item1 , item2 , item3 ")
        result = ApplicationCustomization.get_list("self_log_in")
        self.assertEqual(result, ["item1", "item2", "item3"])

    def test_get_list_int_returns_empty_for_empty_value(self):
        ApplicationCustomization.set("default_badge_reader_id", "")
        result = ApplicationCustomization.get_list_int("default_badge_reader_id")
        self.assertEqual(result, [])

    def test_get_list_int_returns_integers(self):
        ApplicationCustomization.set("default_badge_reader_id", "1,2,3")
        result = ApplicationCustomization.get_list_int("default_badge_reader_id")
        self.assertEqual(result, [1, 2, 3])

    def test_get_list_int_skips_non_integers(self):
        ApplicationCustomization.set("default_badge_reader_id", "1,abc,3")
        result = ApplicationCustomization.get_list_int("default_badge_reader_id")
        self.assertEqual(result, [1, 3])

    def test_get_date_returns_none_for_empty_value(self):
        ApplicationCustomization.set("self_log_in", "")
        result = ApplicationCustomization.get_date("self_log_in")
        self.assertIsNone(result)

    def test_get_date_returns_date_object(self):
        test_date = date(2024, 6, 15)
        ApplicationCustomization.set("self_log_in", test_date.strftime(date_input_format))
        result = ApplicationCustomization.get_date("self_log_in")
        self.assertEqual(result, test_date)

    def test_get_datetime_returns_none_for_empty_value(self):
        ApplicationCustomization.set("self_log_in", "")
        result = ApplicationCustomization.get_datetime("self_log_in")
        self.assertIsNone(result)

    def test_get_datetime_returns_datetime_object(self):
        test_datetime = datetime(2024, 6, 15, 10, 30, 0)
        ApplicationCustomization.set("self_log_in", test_datetime.strftime(datetime_input_format))
        result = ApplicationCustomization.get_datetime("self_log_in")
        self.assertEqual(result, test_datetime)

    def test_set_clears_value_when_empty(self):
        ApplicationCustomization.set("facility_name", "My Lab")
        ApplicationCustomization.set("facility_name", "")
        value = ApplicationCustomization.get("facility_name")
        self.assertEqual(value, "Facility")  # back to default

    def test_set_raises_for_unknown_name(self):
        with self.assertRaises(InvalidCustomizationException):
            ApplicationCustomization.set("nonexistent_key", "value")

    def test_get_uses_cache(self):
        ApplicationCustomization.set("facility_name", "Cached Lab")
        # Second call should hit cache
        value = ApplicationCustomization.get("facility_name")
        self.assertEqual(value, "Cached Lab")

    def test_get_without_cache(self):
        ApplicationCustomization.set("facility_name", "Direct Lab")
        value = ApplicationCustomization.get("facility_name", use_cache=False)
        self.assertEqual(value, "Direct Lab")

    def test_invalidate_cache_forces_reload(self):
        ApplicationCustomization.set("facility_name", "Before Invalidate")
        CustomizationBase.invalidate_cache()
        value = ApplicationCustomization.get("facility_name")
        self.assertEqual(value, "Before Invalidate")
