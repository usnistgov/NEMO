The NEMO web application is laboratory logistics software that strives to be intuitive and easy to use, making life easier in the lab. NEMO manages tool reservations, control access to tools, and streamline logistics and communication. The code is open source and free so that other labs can benefit.

You can try NEMO out using the "[splash pad](https://hub.docker.com/r/nanofab/nemo_splash_pad/)" Docker image, which comes preconfigured and loaded with sample data. Install [Docker Community Edition (CE)](https://www.docker.com/community-edition) and run this command:  
`docker run --detach --name nemo_splash_pad --publish 8000:8000 nanofab/nemo_splash_pad`  
... then open a web browser to http://localhost:8000. You can stop and remove the NEMO splash pad with the command:  
`docker rm --force nemo_splash_pad`

Documentation for NEMO resides in the [GitHub wiki](https://github.com/usnistgov/NEMO/wiki).

You can also download the latest [NEMO Feature Manual](https://github.com/usnistgov/NEMO/raw/master/documentation/NEMO_Feature_Manual.pdf).

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
