import re

from metapet import export
from metapet.model import Idea


def test_links_relative_to_output(store, tmp_path):
    idea = store.create("Budget tracker")
    out = tmp_path / "out"
    out.mkdir()
    text = export.to_markdown([idea], out)
    link = re.search(r"\]\(([^)]+)\)", text).group(1)
    assert "\\" not in link
    assert (out / link).resolve() == idea.path.resolve()


def test_pipe_is_escaped(tmp_path):
    idea = Idea(id="csv", title="CSV | TSV [converter]", tags=["a|b"], path=tmp_path / "csv.md")
    row = next(line for line in export.to_markdown([idea], tmp_path).splitlines() if "CSV" in line)
    assert "[CSV \\| TSV \\[converter\\]](csv.md)" in row
    assert len(re.findall(r"(?<!\\)\|", row)) == 7
