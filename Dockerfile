FROM centos:centos7

RUN yum --assumeyes update
RUN yum --assumeyes install https://centos7.iuscommunity.org/ius-release.rpm
RUN yum --assumeyes install vim python36u python36u-pip

# Intall NEMO (in the current directory) and Gunicorn
COPY . /nemo/
RUN pip3.6 install /nemo/ gunicorn

EXPOSE 8000/tcp
COPY docker_run.sh /usr/local/bin/
RUN chmod +x docker_run.sh
CMD ["docker_run.sh"]