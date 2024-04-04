[![Code style: black](https://img.shields.io/badge/python%20style-black-000000.svg)](https://github.com/psf/black)
[![Code style: djlint](https://img.shields.io/badge/html%20style-djlint-black.svg)](https://www.djlint.com)

[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/NEMO?label=python)](https://www.python.org/downloads/release/python-380/)
[![Docker Image Version (latest semver)](https://img.shields.io/docker/v/nanofab/nemo?label=NEMO%20docker%20version)](https://hub.docker.com/r/nanofab/nemo)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/usnistgov/nemo?label=NEMO%20github%20version)](https://github.com/usnistgov/NEMO/releases)
[![PyPI](https://img.shields.io/pypi/v/nemo?label=NEMO%20pypi%20version)](https://pypi.org/project/NEMO/)

The NEMO web application is laboratory logistics software that strives to be intuitive and easy to use, making life easier in the lab. NEMO manages tool reservations, control access to tools, and streamline logistics and communication. The code is open source and free so that other labs can benefit.

# Online demo
An online version of the splash pad is available on a third party website at [https://nemo-demo.atlantislabs.io](https://nemo-demo.atlantislabs.io).

### User roles
You will be automatically logged in as superadmin "captain".<br>
Use the [impersonate](https://nemo-demo.atlantislabs.io/impersonate) feature to switch between user roles:
* `Ned Land`: regular user
* `Pierre Aronnax`: staff member
* `Assistant Conseil`: user office
* `Commander Farragut`: accounting
* `Captain Nemo`: super admin

### Jumbotron
The jumbotron is available at [https://nemo-demo.atlantislabs.io/jumbotron/](https://nemo-demo.atlantislabs.io/jumbotron/)

### Kiosk/Area access
You can test the kiosk and area access features by going to the following URLs:
* [entry door](https://nemo-demo.atlantislabs.io/welcome_screen/1/?occupancy=Cleanroom)
* [exit door](https://nemo-demo.atlantislabs.io/farewell_screen/1/?occupancy=Cleanroom)
* [kiosk](https://nemo-demo.atlantislabs.io/kiosk/NanoFab/?occupancy=Cleanroom)

To simulate the badge reader, press `F2` then the badge number (`1` for captain, `2` for professor, `3` for ned) and press `F2` again.

# On premise demo
You can try NEMO out using the "[splash pad](https://hub.docker.com/r/nanofab/nemo_splash_pad/)" Docker image, which comes preconfigured and loaded with sample data. Install [Docker Community Edition (CE)](https://www.docker.com/community-edition) and run this command:  
`docker run --detach --name nemo_splash_pad --publish 8000:8000 nanofab/nemo_splash_pad`  
... then open a web browser to http://localhost:8000. You can stop and remove the NEMO splash pad with the command:  
`docker rm --force nemo_splash_pad`

# Documentation

Documentation for NEMO resides in the [GitHub wiki](https://github.com/usnistgov/NEMO/wiki).

You can also download the latest [NEMO Feature Manual](https://nemo.nist.gov/public/NEMO_Feature_Manual.pdf) and the [NEMO Hardware Accessories](https://nemo.nist.gov/public/NEMO_Hardware_Accessories.pdf) document.

If you're interested in deploying NEMO at your organization, there are [deployment considerations](https://github.com/usnistgov/NEMO/wiki/Deployment-considerations) documented in the wiki. This covers what infrastructure you will need in order to have a robust production-level deployment. The [installation guide](https://github.com/usnistgov/NEMO/wiki/Installation-with-Docker) provides a step-by-step guide to deploying NEMO.

The [community page](https://github.com/usnistgov/NEMO/wiki/Community) outlines how to ask questions and contribute to NEMO. Bugs can be reported to the [issues page](https://github.com/usnistgov/NEMO/issues). If you've found a security issue with NEMO then please read our [security policy](https://github.com/usnistgov/NEMO/wiki/Security-policy) and tell us discretely.

# Screenshots

Here are some sample screenshots showing some of NEMO's primary features.

_Landing page - the first thing a user sees when visiting NEMO_
![Landing page](/documentation/landing_page.png "Landing page")

_Calendar - manage tool reservations_
![Calendar](/documentation/calendar.png "Calendar")

_Tool control (with hardware interlocks) - enable or disable tools, report problems, view tool status_
![Tool control](/documentation/tool_control.png "Tool control")

_Maintenance tasks_
![Maintenance tasks](/documentation/maintenance.png "Maintenance tasks")
