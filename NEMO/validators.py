import re

from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _

COLOR_HEX_RE = "#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})"


color_hex_validator = RegexValidator(
    re.compile(r"^" + COLOR_HEX_RE + "$"),
    _("Enter a valid hex color, eg. #000000"),
    "invalid",
)


color_hex_list_validator = RegexValidator(
    re.compile(r"^" + COLOR_HEX_RE + "(?:,\s*" + COLOR_HEX_RE + ")*$"),
    message=_("Enter a valid hex color list, eg. #000000,#111111"),
    code="invalid",
)
