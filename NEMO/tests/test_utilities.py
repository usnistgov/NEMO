from NEMO.models import User


def login_as_staff(client):
	tester = User.objects.create(username='test_staff', first_name='Test', last_name='Staff', is_staff=True)
	client.force_login(user=tester)