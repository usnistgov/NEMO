from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from NEMO.models import User
from NEMO.tests.test_utilities import login_as_user

request_content_type = "application/json"


class RestCRUDTestCase(TestCase):
	def test_user_list(self):
		list_url = reverse("user-list")
		user = login_as_user(self.client)
		response = self.client.get(list_url, follow=True)
		self.assertEqual(response.status_code, 403)
		user.user_permissions.add(Permission.objects.get(codename="view_user"))
		response = self.client.get(list_url, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, '"id":')
		self.assertContains(response, '"username":')

	def test_user_view(self):
		user = login_as_user(self.client)
		retrieve_url = reverse("user-detail", args=[1])
		response = self.client.get(retrieve_url, follow=True)
		self.assertEqual(response.status_code, 403)
		user.user_permissions.add(Permission.objects.get(codename="view_user"))
		response = self.client.get(retrieve_url, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertTrue(response.data["id"])
		self.assertTrue(response.data["first_name"])
		self.assertTrue(response.data["last_name"])

	def test_save_user(self):
		save_url = reverse("user-list")
		data = {"first_name": "John"}
		user = login_as_user(self.client)
		response = self.client.post(save_url, data, follow=True)
		self.assertEqual(response.status_code, 403)
		user.user_permissions.add(Permission.objects.get(codename="add_user"))
		response = self.client.post(save_url, data, follow=True)
		self.assertEqual(response.status_code, 400)
		self.assertTrue("username" in response.data)
		self.assertTrue("last_name" in response.data)
		self.assertTrue("email" in response.data)
		data["last_name"] = "Doe"
		data["username"] = "jdoe"
		data["email"] = "jdoe@doe.com"
		response = self.client.post(save_url, data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data["first_name"], "John")
		self.assertEqual(response.data["last_name"], "Doe")
		self.assertEqual(response.data["username"], "jdoe")
		self.assertEqual(response.data["email"], "jdoe@doe.com")

	def test_update_user(self):
		user = login_as_user(self.client)
		user.user_permissions.add(Permission.objects.get(codename="view_user"))
		user.user_permissions.add(Permission.objects.get(codename="add_user"))
		user_data = {"first_name": "John", "last_name": "Doe", "username": "jdoe", "email": "jdoe@doe.com"}
		data = self.client.post(reverse("user-list"), user_data).data
		update_url = reverse("user-detail", args=[data["id"]])
		response = self.client.put(update_url, data, follow=True)
		self.assertEqual(response.status_code, 403)
		user.user_permissions.add(Permission.objects.get(codename="change_user"))
		data["username"] = ""
		data["email"] = ""
		response = self.client.put(update_url, data, follow=True, content_type=request_content_type)
		self.assertEqual(response.status_code, 400)
		self.assertTrue("username" in response.data)
		self.assertTrue("email" in response.data)
		data["username"] = "jode1"
		data["email"] = "jdoe1@doe.com"
		response = self.client.put(update_url, data, follow=True, content_type=request_content_type)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data["username"], "jode1")
		for key in data:
			if key != "username":
				self.assertEqual(response.data[key], data[key])

	def test_partial_update_user(self):
		user = login_as_user(self.client)
		user.user_permissions.add(Permission.objects.get(codename="add_user"))
		user_data = {"first_name": "John", "last_name": "Doe", "username": "jdoe", "email": "jdoe@doe.com"}
		data = self.client.post(reverse("user-list"), user_data).data
		update_url = reverse("user-detail", args=[data["id"]])
		partial_data = {"username": "jdoe1"}
		response = self.client.patch(update_url, partial_data, follow=True, content_type=request_content_type)
		self.assertEqual(response.status_code, 403)
		user.user_permissions.add(Permission.objects.get(codename="change_user"))
		response = self.client.patch(update_url, partial_data, follow=True, content_type=request_content_type)
		self.assertEqual(response.status_code, 200)
		self.assertTrue("username" in response.data)
		self.assertEqual(response.data["username"], "jdoe1")
		for key in data:
			if key != "username":
				self.assertEqual(response.data[key], data[key])

	def test_delete_user(self):
		user = login_as_user(self.client)
		user.user_permissions.add(Permission.objects.get(codename="add_user"))
		user_data = {"first_name": "John", "last_name": "Doe", "username": "jdoe", "email": "jdoe@doe.com"}
		data = self.client.post(reverse("user-list"), user_data).data
		delete_url = reverse("user-detail", args=[data["id"]])
		response = self.client.delete(delete_url, follow=True)
		self.assertEqual(response.status_code, 403)
		user.user_permissions.add(Permission.objects.get(codename="delete_user"))
		response = self.client.delete(delete_url, follow=True)
		self.assertEqual(response.status_code, 204)
		self.assertRaises(User.DoesNotExist, User.objects.get, username="jdoe")
