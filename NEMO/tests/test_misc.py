import re

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from NEMO.models import Tool, UserKnowledgeBaseCategory, UserKnowledgeBaseItem, UserKnowledgeBaseItemDocuments
from NEMO.tests.test_utilities import NEMOTestCaseMixin, create_user_and_project
from NEMO.utilities import capitalize, get_email_from_settings, is_same_origin, resize_image


class MiscTests(NEMOTestCaseMixin, TestCase):
    def test_capitalize(self):
        self.assertEqual(capitalize(None), None)
        self.assertEqual(capitalize(""), "")
        self.assertEqual(capitalize("j"), "J")
        self.assertEqual(capitalize("John Doe"), "John Doe")
        self.assertEqual(capitalize("john Doe"), "John Doe")
        self.assertEqual(capitalize("john doe"), "John doe")
        self.assertEqual(capitalize("john DOE"), "John DOE")

    def test_server_email(self):
        default_from = "email@example.com"
        self.assertEqual(get_email_from_settings(), settings.SERVER_EMAIL)
        with self.settings(DEFAULT_FROM_EMAIL=default_from):
            self.assertEqual(get_email_from_settings(), default_from)

    def test_resize_image(self):
        image_path = settings.BASE_DIR + "/../resources/images/jumbotron_watermark.png"
        image = Image.open(image_path)
        width, height = image.size
        image.close()
        resized = resize_image(open(image_path, "rb"), 40)
        resized_image = Image.open(resized)
        resized_width, resized_height = resized_image.size
        if width > height:
            self.assertEqual(resized_width, 40)
        else:
            self.assertEqual(resized_height, 40)
        resized_image.close()

    def test_regex_escaping(self):
        # non escaped, no match
        self.assertFalse(re.match("test?[]]", "test?[]]"))
        # escaped, match
        self.assertTrue(re.match(re.escape("test?[]]"), "test?[]]"))
        # escaped + number
        self.assertTrue(re.match(re.escape("test?[]]") + r"\d+$", "test?[]]5"))
        self.assertTrue(re.match(re.escape("test?[]]") + r"\d+$", "test?[]]124"))
        # number is mandatory
        self.assertFalse(re.match(re.escape("test?[]]") + r"\d+$", "test?[]]"))

    def test_is_same_origin(self):
        request = RequestFactory().get("/")
        # Relative URLs
        self.assertTrue(is_same_origin("/media/documents/guide.pdf"))
        self.assertTrue(is_same_origin("media/documents/guide.pdf"))
        # Protocol-relative URLs pointing to external hosts
        self.assertFalse(is_same_origin("//external.com/guide.pdf"))
        # Empty/None
        self.assertFalse(is_same_origin(""))
        self.assertFalse(is_same_origin(None))

        # Absolute URL with default testserver host
        self.assertTrue(is_same_origin("http://testserver/media/guide.pdf", request))

        # Allowed hosts and server domain
        with override_settings(
            ALLOWED_HOSTS=["nemo.nist.gov", ".example.org"], SERVER_DOMAIN="https://nemo.nist.gov:8080"
        ):
            self.assertTrue(is_same_origin("https://nemo.nist.gov/media/guide.pdf"))
            self.assertTrue(is_same_origin("https://nemo.nist.gov:8080/media/guide.pdf"))
            self.assertTrue(is_same_origin("https://sub.example.org/media/guide.pdf"))
            self.assertFalse(is_same_origin("https://otherdomain.com/media/guide.pdf"))

        # Extra hosts
        self.assertTrue(
            is_same_origin(
                "https://s3.amazonaws.com/media/guide.pdf", extra_hosts=["s3.amazonaws.com", ".cdn.example.org"]
            )
        )
        self.assertTrue(
            is_same_origin(
                "https://assets.cdn.example.org/video.mp4", extra_hosts=["s3.amazonaws.com", ".cdn.example.org"]
            )
        )
        self.assertFalse(
            is_same_origin(
                "https://otherdomain.com/media/guide.pdf", extra_hosts=["s3.amazonaws.com", ".cdn.example.org"]
            )
        )


class IsEmptyLookupTests(NEMOTestCaseMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        # 1. The "True NULL" Record
        cls.null_record = Tool.objects.create(name="null record", _serial=None, _description=None)

        # 2. The "Empty String" Record
        # (Oracle treats char_field '' as NULL, but text_field as an empty CLOB)
        cls.empty_string_record = Tool.objects.create(name="empty record", _serial="", _description="")

        # 3. The "Populated" Record
        cls.populated_record = Tool.objects.create(name="populated record", _serial="Data", _description="Data")

    # --- TESTING TRUE (Looking for empty values) ---
    def test_char_field_isempty_true(self):
        """Should return records where char_field is NULL or ''"""
        results = Tool.objects.filter(_serial__isempty=True)
        self.assertEqual(results.count(), 2)
        self.assertIn(self.null_record, results)
        self.assertIn(self.empty_string_record, results)

    def test_text_field_isempty_true(self):
        """Should return records where text_field is NULL or an empty CLOB"""
        results = Tool.objects.filter(_description__isempty=True)
        self.assertEqual(results.count(), 2)
        self.assertIn(self.null_record, results)
        self.assertIn(self.empty_string_record, results)

    # --- TESTING FALSE (Looking for populated values) ---
    def test_char_field_isempty_false(self):
        """Should ONLY return the record with actual text in the char_field"""
        results = Tool.objects.filter(_serial__isempty=False)
        self.assertEqual(results.count(), 1)
        self.assertIn(self.populated_record, results)

    def test_text_field_isempty_false(self):
        """Should ONLY return the record with actual text in the text_field"""
        results = Tool.objects.filter(_description__isempty=False)
        self.assertEqual(results.count(), 1)
        self.assertIn(self.populated_record, results)


class DocumentEmbeddingTests(NEMOTestCaseMixin, TestCase):
    def setUp(self):
        self.user, _ = create_user_and_project()
        self.kb_cat = UserKnowledgeBaseCategory.objects.create(name="Cat", display_order=1)
        self.kb_item = UserKnowledgeBaseItem.objects.create(name="Item", category=self.kb_cat, display_order=1)

    def test_can_be_embedded_file_vs_url(self):
        pdf_file = SimpleUploadedFile("guide.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        doc_file = UserKnowledgeBaseItemDocuments.objects.create(item=self.kb_item, document=pdf_file)
        self.assertTrue(doc_file.can_be_embedded())

        docx_file = SimpleUploadedFile(
            "guide.docx",
            b"test",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        doc_docx = UserKnowledgeBaseItemDocuments.objects.create(item=self.kb_item, document=docx_file)
        self.assertFalse(doc_docx.can_be_embedded())

        # Same origin relative URL PDF
        doc_url_rel_pdf = UserKnowledgeBaseItemDocuments.objects.create(
            item=self.kb_item, url="/media/documents/guide.pdf"
        )
        self.assertTrue(doc_url_rel_pdf.can_be_embedded())

        # Cross origin URL PDF
        doc_url_ext_pdf = UserKnowledgeBaseItemDocuments.objects.create(
            item=self.kb_item, url="https://external.com/guide.pdf"
        )
        self.assertFalse(doc_url_ext_pdf.can_be_embedded())

        # Same origin URL with allowed host in settings
        with override_settings(ALLOWED_HOSTS=["nemo.nist.gov"], SERVER_DOMAIN="https://nemo.nist.gov"):
            doc_url_allowed_pdf = UserKnowledgeBaseItemDocuments.objects.create(
                item=self.kb_item, url="https://nemo.nist.gov/guide.pdf"
            )
            self.assertTrue(doc_url_allowed_pdf.can_be_embedded())

        # Embeddable document hosts in settings
        with override_settings(EMBEDDABLE_DOCUMENT_HOSTS=["s3.amazonaws.com"]):
            doc_url_embed_pdf = UserKnowledgeBaseItemDocuments.objects.create(
                item=self.kb_item, url="https://s3.amazonaws.com/guide.pdf"
            )
            self.assertTrue(doc_url_embed_pdf.can_be_embedded())

        # Same origin URL with unsupported extension
        doc_url_other = UserKnowledgeBaseItemDocuments.objects.create(
            item=self.kb_item, url="/media/documents/page.html"
        )
        self.assertFalse(doc_url_other.can_be_embedded())

    def test_media_view_embedding(self):
        self.login_as(self.user)
        pdf_file = SimpleUploadedFile("guide.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        doc_file = UserKnowledgeBaseItemDocuments.objects.create(item=self.kb_item, document=pdf_file)
        content_type = ContentType.objects.get_for_model(UserKnowledgeBaseItemDocuments)

        # Uploaded PDF file should succeed in media_view
        response = self.client.get(
            reverse(
                "media_view", kwargs={"popup": "true", "content_type_id": content_type.id, "document_id": doc_file.id}
            )
        )
        self.assertEqual(response.status_code, 200)

        # Same-origin relative URL PDF should succeed in media_view
        doc_url_same_origin = UserKnowledgeBaseItemDocuments.objects.create(
            item=self.kb_item, url="/media/documents/guide.pdf"
        )
        response = self.client.get(
            reverse(
                "media_view",
                kwargs={"popup": "true", "content_type_id": content_type.id, "document_id": doc_url_same_origin.id},
            )
        )
        self.assertEqual(response.status_code, 200)

        # Same-origin absolute URL matching request host should succeed in media_view
        doc_url_testserver = UserKnowledgeBaseItemDocuments.objects.create(
            item=self.kb_item, url="http://testserver/media/guide.pdf"
        )
        response = self.client.get(
            reverse(
                "media_view",
                kwargs={"popup": "true", "content_type_id": content_type.id, "document_id": doc_url_testserver.id},
            )
        )
        self.assertEqual(response.status_code, 200)

        # Cross-origin URL PDF should return 400 Bad Request
        doc_url_pdf = UserKnowledgeBaseItemDocuments.objects.create(
            item=self.kb_item, url="https://external.com/guide.pdf"
        )
        response = self.client.get(
            reverse(
                "media_view",
                kwargs={"popup": "true", "content_type_id": content_type.id, "document_id": doc_url_pdf.id},
            )
        )
        self.assertEqual(response.status_code, 400)

        # Cross-origin URL PDF with EMBEDDABLE_DOCUMENT_HOSTS should succeed in media_view
        with override_settings(EMBEDDABLE_DOCUMENT_HOSTS=["external.com"]):
            response = self.client.get(
                reverse(
                    "media_view",
                    kwargs={"popup": "true", "content_type_id": content_type.id, "document_id": doc_url_pdf.id},
                )
            )
            self.assertEqual(response.status_code, 200)
