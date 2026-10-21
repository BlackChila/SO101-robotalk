"""Exercise broken links, anchors, references and fenced examples."""

import tempfile
import unittest
from pathlib import Path

from check_docs import check_file, heading_anchors


class DocumentationChecks(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.document = self.root / "README.md"

    def check(self, content):
        self.document.write_text(content, encoding="utf-8")
        return check_file(self.document, self.root, {})

    def test_missing_file_and_anchor_are_reported(self):
        (self.root / "guide.md").write_text("# Installation\n", encoding="utf-8")
        errors = self.check("[missing](missing.md)\n[wrong section](guide.md#missing)\n")
        self.assertEqual(len(errors), 2)
        self.assertIn("missing file", errors[0])
        self.assertIn("missing anchor", errors[1])

    def test_real_paths_encoded_spaces_and_duplicate_headings(self):
        (self.root / "a guide.md").write_text("# Setup\n# Setup\n", encoding="utf-8")
        self.assertEqual(self.check("[guide](a%20guide.md#setup-1)\n[guide](<a guide.md#setup>)\n"), [])

    def test_examples_inline_code_and_external_urls_are_not_local_links(self):
        text = """[external](https://example.com/no-request)
`[example](missing.md)`
   ```markdown
   [example](missing.md)
   # Hidden heading
   ```
~~~markdown
[another](absent.md)
~~~
"""
        self.assertEqual(self.check(text), [])
        self.assertNotIn("hidden-heading", heading_anchors(text))

    def test_reference_links_and_explicit_anchors(self):
        (self.root / "guide.md").write_text('<a id="custom"></a>\n# Guide\n', encoding="utf-8")
        self.assertEqual(self.check("[details][guide]\n[guide][]\n[guide]\n[guide]: guide.md#custom\n"), [])
        self.assertIn("undefined reference", self.check("[details][absent]\n")[0])

    def test_link_cannot_point_outside_the_repository(self):
        self.assertIn("leaves the repository", self.check("[outside](../private.md)\n")[0])

    def test_unicode_and_repeated_heading_slugs(self):
        self.assertEqual(heading_anchors("# Über Setup\n# **Über** Setup\n# A `name`\n"),
                         {"über-setup", "über-setup-1", "a-name"})


if __name__ == "__main__":
    unittest.main()
