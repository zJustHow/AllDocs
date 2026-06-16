FROM docker.elastic.co/elasticsearch/elasticsearch:8.15.0

USER root
RUN bin/elasticsearch-plugin install -b \
    https://get.infini.cloud/elasticsearch/analysis-ik/8.15.0
USER elasticsearch
