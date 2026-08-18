FROM postgres:16-alpine

COPY operations/local-operations.sh /usr/local/bin/prem-engine-operations

RUN chmod 0555 /usr/local/bin/prem-engine-operations

ENTRYPOINT ["/usr/local/bin/prem-engine-operations"]
CMD ["diagnostics"]
