import unittest

from wayhint.config import ConfigError, parse_global_config
from wayhint.i18n import EN, JA, detect_language, translator


class I18nTest(unittest.TestCase):
    def test_detect_language_precedence(self) -> None:
        self.assertEqual(detect_language({"LANG": "ja_JP.UTF-8"}), "ja")
        self.assertEqual(
            detect_language({"LANG": "ja_JP.UTF-8", "LC_MESSAGES": "en_US.UTF-8"}), "en"
        )
        self.assertEqual(detect_language({"LANG": "ja_JP.UTF-8", "LC_ALL": "de_DE@euro"}), "de")
        self.assertEqual(detect_language({"LANG": "C.UTF-8"}), "en")
        self.assertEqual(detect_language({}), "en")

    def test_translator_auto_and_fallbacks(self) -> None:
        self.assertEqual(translator("auto", {"LANG": "ja_JP.UTF-8"})("Search"), "検索")
        self.assertEqual(translator("auto", {"LANG": "fr_FR.UTF-8"})("Search"), "Search")
        self.assertEqual(translator("ja")("Close"), "閉じる")
        self.assertEqual(translator("ja")("not a key"), "not a key")
        self.assertEqual(translator("ja")("… and {n} more").format(n=2), "… 他 2 件")

    def test_catalogs_cover_the_same_keys(self) -> None:
        self.assertEqual(set(JA), set(EN))

    def test_config_language(self) -> None:
        self.assertEqual(parse_global_config({}).language, "auto")
        self.assertEqual(parse_global_config({"appearance": {"language": "ja"}}).language, "ja")
        with self.assertRaises(ConfigError):
            parse_global_config({"appearance": {"language": "xx"}})


if __name__ == "__main__":
    unittest.main()
