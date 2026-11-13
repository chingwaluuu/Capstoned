"""Expected output checks for the safe inline MathML renderer."""

import unittest

from math_render import render_math


def math(body: str) -> str:
    return f'<math display="inline"><mrow>{body}</mrow></math>'


class MathRenderTest(unittest.TestCase):
    def test_separate_fractions_in_prose(self):
        self.assertEqual(
            str(render_math("giving 1/9 and 2/9 respectively")),
            "giving " + math("<mfrac><mn>1</mn><mn>9</mn></mfrac>")
            + " and " + math("<mfrac><mn>2</mn><mn>9</mn></mfrac>") + " respectively",
        )

    def test_equations_and_trailing_period(self):
        result = str(render_math(
            "setting 10x = 1.111... and subtracting x = 0.111... gives 9x = 1, "
            "so x = 1/9."
        ))
        self.assertEqual(
            result,
            "setting " + math("<mn>10</mn><mi>x</mi><mo>=</mo><mn>1.</mn><mover accent=\"true\"><mn>1</mn><mo>¯</mo></mover>")
            + " and subtracting " + math("<mi>x</mi><mo>=</mo><mn>0.</mn><mover accent=\"true\"><mn>1</mn><mo>¯</mo></mover>")
            + " gives " + math("<mn>9</mn><mi>x</mi><mo>=</mo><mn>1</mn>")
            + ", so " + math("<mi>x</mi><mo>=</mo><mfrac><mn>1</mn><mn>9</mn></mfrac>") + ".",
        )

    def test_mixed_number_parentheses_spaced_division_and_equation_chain(self):
        result = str(render_math(
            "rewriting 1.333... as 1 3/9, which becomes (9 * 1 + 3) / 9 = 12/9 = 4/3"
        ))
        self.assertEqual(
            result,
            "rewriting " + math("<mn>1.</mn><mover accent=\"true\"><mn>3</mn><mo>¯</mo></mover>") + " as "
            + math("<mn>1</mn><mfrac><mn>3</mn><mn>9</mn></mfrac>")
            + ", which becomes "
            + math(
                "<mfrac><mrow><mo>(</mo><mn>9</mn><mo>×</mo><mn>1</mn><mo>+</mo>"
                "<mn>3</mn><mo>)</mo></mrow><mrow><mn>9</mn></mrow></mfrac>"
                "<mo>=</mo><mfrac><mn>12</mn><mn>9</mn></mfrac><mo>=</mo>"
                "<mfrac><mn>4</mn><mn>3</mn></mfrac>"
            ),
        )

    def test_long_equation_sequence(self):
        result = str(render_math(
            "you set 100x = 21.111... and 10x = 2.111..., subtract them to get "
            "90x = 19, resulting in x = 19/90."
        ))
        self.assertIn(math("<mn>100</mn><mi>x</mi><mo>=</mo><mn>21.</mn><mover accent=\"true\"><mn>1</mn><mo>¯</mo></mover>"), result)
        self.assertIn(math("<mn>10</mn><mi>x</mi><mo>=</mo><mn>2.</mn><mover accent=\"true\"><mn>1</mn><mo>¯</mo></mover>"), result)
        self.assertIn(math("<mn>90</mn><mi>x</mi><mo>=</mo><mn>19</mn>"), result)
        self.assertIn(math("<mi>x</mi><mo>=</mo><mfrac><mn>19</mn><mn>90</mn></mfrac>"), result)

    def test_repeating_bar_starts_after_nonrepeating_decimal_digits(self):
        self.assertEqual(
            str(render_math("0.2111...")),
            math("<mn>0.2</mn><mover accent=\"true\"><mn>1</mn><mo>¯</mo></mover>"),
        )

    def test_non_math_prose_and_page_ranges_are_unchanged(self):
        self.assertEqual(str(render_math("non-terminating, repeating decimals")), "non-terminating, repeating decimals")
        self.assertEqual(str(render_math("Source: pp. 17-21")), "Source: pp. 17-21")
        self.assertEqual(str(render_math("There are 9 apples.")), "There are 9 apples.")

    def test_escape_html_before_math_conversion(self):
        self.assertEqual(
            str(render_math("9 apples & <script>alert(1)</script>")),
            "9 apples &amp; &lt;script&gt;alert(1)&lt;/script&gt;",
        )


if __name__ == "__main__":
    unittest.main()
