FROM postgres:16-alpine

COPY operations/local-operations.sh /usr/local/bin/prem-engine-operations

RUN sed -i 's/\r$//' /usr/local/bin/prem-engine-operations \
    && chmod 0555 /usr/local/bin/prem-engine-operations

ENTRYPOINT ["/usr/local/bin/prem-engine-operations"]
CMD ["diagnostics"]
