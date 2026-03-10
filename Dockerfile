FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive
ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8

RUN apt-get update && \
    apt-get install -y \
        build-essential \
        bc \
        coq \
        libxml2-dev \
        libxslt1-dev \
        libhdf5-dev \
        pkg-config \
        python3 \
        python3-pip \
        python3-dev \
        python-is-python3 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Build C&C Parser
COPY third-party/candc/candc-1.00.tgz /tmp/
COPY third-party/candc/models-1.02.tgz /tmp/
WORKDIR /opt
RUN tar -xzf /tmp/candc-1.00.tgz && \
    tar -xzf /tmp/models-1.02.tgz && \
    mv models candc-1.00/
WORKDIR /opt/candc-1.00
RUN sed -i 's|CXXFLAGS = \$(CFLAGS)|CXXFLAGS = \$(CFLAGS) -std=c++98 -fpermissive|' Makefile.unix && \
    find src/include -name "*.h" -exec sed -i '1i#include <cstring>' {} \; && \
    find src/lib -name "*.cc" -exec grep -l "memset\|memmove\|strcpy\|strlen" {} \; | xargs -I {} sed -i '1i#include <cstring>' {} && \
    sed -i 's|str == this->str|str == std::string(this->str.str())|' src/include/hashtable/word.h && \
    make -f Makefile.unix && \
    rm -f /tmp/*.tgz

WORKDIR /opt

# Install Python dependencies
RUN pip3 install --upgrade pip "setuptools<=68.2.2" wheel
RUN pip3 install --no-cache-dir "cython==0.29.30" "numpy==1.23.5" lxml pyyaml simplejson
RUN pip3 install --no-cache-dir "cached-path==1.1.2"
RUN pip3 install --no-cache-dir "h5py==3.7.0"
RUN pip3 install --no-cache-dir "depccg==2.0.3.2"
RUN pip3 uninstall -y importlib-metadata importlib_metadata || true \
    && pip3 install --no-cache-dir importlib-metadata==4.13.0
RUN pip3 install --no-cache-dir "nltk==3.0.5"
RUN python -c "import nltk; nltk.download('wordnet')"

# Install depccg models
COPY third-party/depccg/tri_headfirst.tar.gz /tmp/
RUN DEPCCG_PATH=$(python -c "import depccg; import os; print(os.path.dirname(depccg.__file__))") && \
    mkdir -p $DEPCCG_PATH/models && \
    tar -xzf /tmp/tri_headfirst.tar.gz -C $DEPCCG_PATH/models && \
    rm -f /tmp/tri_headfirst.tar.gz

# Copy application
WORKDIR /app
COPY . /app

# Configure parser locations
RUN echo "/opt/candc-1.00" > en/candc_location.txt && \
    echo "depccg:" > en/parser_location.txt

# Compile Coq library and generate Coq 8.11-compatible tactics
RUN cp ./en/coqlib_sick.v ./coqlib.v && coqc coqlib.v && \
    echo 'nltac. Qed' > ./tactics_coq.txt

CMD ["/bin/bash"]
