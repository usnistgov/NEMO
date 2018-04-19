FROM centos:centos7

RUN yum --assumeyes update
RUN yum --assumeyes install https://centos7.iuscommunity.org/ius-release.rpm
RUN yum --assumeyes install vim python36u python36u-pip

# Intall NEMO (in the current directory) and Gunicorn
COPY . /nemo/
RUN pip3.6 install /nemo/ gunicorn
RUN rm --recursive --force /nemo/

RUN mkdir /nemo
ENV DJANGO_SETTINGS_MODULE "settings"
ENV PYTHONPATH "/nemo/"

EXPOSE 8000/tcp

COPY start_NEMO_in_Docker.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/start_NEMO_in_Docker.sh
CMD ["start_NEMO_in_Docker.sh"]
