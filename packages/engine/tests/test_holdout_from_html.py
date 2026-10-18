"""bench/holdout_from_html.py reads back exactly the diff the report rendered."""
from bench import holdout_from_html as h
from nge import report_html

PATCH = ("--- a/pkg/m.py\n+++ b/pkg/m.py\n@@ -1,3 +1,3 @@\n def f(a, b):\n"
         "-    return a < b and '<&>'\n+    return a <= b and \"<&>\"\n \n")


def test_the_rendered_diff_reads_back_byte_for_byte():
    row = (f'<code>pkg/tests/test_m.py::test_f</code><details><summary>patch</summary>'
           f'<pre class="diff">{report_html._diff_html(PATCH)}</pre></details>')
    assert h.diffs_from_html(row) == {"pkg/tests/test_m.py::test_f": PATCH}


def test_verified_tests_come_from_the_event_log():
    md = '# r\n```json\n[{"kind": "fix_verified", "test": "a::b"}, {"kind": "fix_rejected", "test": "c::d"}]\n```\n'
    assert h.verified_tests(md) == ["a::b"]
