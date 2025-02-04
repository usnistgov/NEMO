# Maximum length for additional information of reservations
ADDITIONAL_INFORMATION_MAXIMUM_LENGTH = 3000

# Maximum length for feedback emails
FEEDBACK_MAXIMUM_LENGTH = 5000

# Multiple useful lengths for Char fields (previous DB limitation is not valid nowadays)
CHAR_FIELD_SMALL_LENGTH = 100
CHAR_FIELD_MEDIUM_LENGTH = 255
CHAR_FIELD_LARGE_LENGTH = 1024
# Kept for backward compatibility
CHAR_FIELD_MAXIMUM_LENGTH = CHAR_FIELD_MEDIUM_LENGTH

# Name of the parameter to indicate which view to redirect to
NEXT_PARAMETER_NAME = "next"

# Name of the media folder under which only staff can see files
MEDIA_PROTECTED = "protected"
