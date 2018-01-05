FROM centos:centos7

RUN yum -y update

# Install utility tools
RUN yum -y install vim

# Install Python3
RUN yum -y install https://centos7.iuscommunity.org/ius-release.rpm && \
    yum -y install python36u

# Install Pip
RUN yum -y install python36u-pip

# User Python3 as default Python
RUN echo "alias python=python3.6" >> ~/.bashrc
RUN echo "alias pip=pip3.6" >> ~/.bashrc

# Install NEMO

# NEMO source code dir
ENV SRC_PATH /root/src
# NEMO running dir
ENV NEMO_PATH /nemo

ENV NEMO_PYTHON python3.6
ENV NEMO_PIP pip3.6

WORKDIR $SRC_PATH

# Copy NEMO source code
COPY . $SRC_PATH

# Copy scripts to NEMO_PATH
COPY ./scripts $NEMO_PATH/scripts

# Intall NEMO
RUN $NEMO_PIP install .

# Install Gunicorn
RUN $NEMO_PIP install gunicorn

WORKDIR $NEMO_PATH

# Remove NEMO source code
RUN rm -rf $SRC_PATH

# Start NEMO
RUN chmod +x ./scripts/nemo_start.sh
CMD ["./scripts/nemo_start.sh"]
