import elasticsearch
import traceback
import paramiko
import sqlite3
import time
from datetime import datetime
from connectivity import do_wrapper

elastic = elasticsearch.Elasticsearch(["es.lab.grds.io:9200"])


def add_args(parser):
    parser.add_argument("--esimport", help="Import the workspace into Elasticsearch", action="store_true")


def parse_args(args, config):
    if args.esimport:
        if args.workspace is not None:
            reconng_import(args, config)


def add_host(ip_address, hostname, source, workspace):
    body = {"ip_address": ip_address, "hostname": hostname, "source": source, "workspace": workspace,
            "timestamp": datetime.utcnow()}
    elastic.index(index="bug_bounty", doc_type="host", body=body)


def reconng_import(args, config):
    host_dict = {}
    workspace = args.workspace

    # If we're given --droplet, collect the DB remotely
    # Otherwise assume the file is already local
    if args.droplet is not None:
        droplet = do_wrapper.get_droplet(args.droplet, config)

        # Setup SSH
        ssh_key_filename = config.get("DigitalOcean", "ssh_key_filename")
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        print("Connecting to the droplet...")
        ssh.connect(droplet.ip_address, username="root", key_filename=ssh_key_filename)

        # Collect recon-ng db file
        print("Downloading recon-ng db...")
        sftp = ssh.open_sftp()
        sftp.chdir("/root/.recon-ng/workspaces/{}".format(workspace))
        sftp.get("data.db", "{}.db".format(workspace))

    # Build the DB and create session object and connect to downloaded db
    conn = sqlite3.connect('{}.db'.format(workspace))
    cursor = conn.cursor()

    # Iterate through recon-ng db and add host data to recon.db
    print("Pulling data from recon-ng db to local db...")
    new_hosts = 0
    duplicate_hosts = 0

    for row in cursor.execute("select * from hosts"):
        hostname = str(row[0])
        ip_address = str(row[1])
        source = str(row[6])

        # If the hostname has never been seen, add to dict and add as a host
        if hostname not in host_dict.keys():
            host_dict[hostname] = []
            host_dict[hostname].append(ip_address)
            add_host(ip_address, hostname, source, workspace)
            new_hosts += 1

        # If the host has been seen, but the IP has not
        elif ip_address not in host_dict[hostname]:
            add_host(ip_address, hostname, source, workspace)
            new_hosts += 1

        else:
            duplicate_hosts += 1

        print("{} new hosts, {} duplicate hosts".format(new_hosts, duplicate_hosts), end="\r")
    print("{} new hosts, {} duplicate hosts".format(new_hosts, duplicate_hosts))


def create_index():
    try:
        host_mapping = {
            "host": {
                "properties": {
                    "ip_address": {"type": "string"},
                    "source": {"type": "string"},
                    "workspace": {"type": "string"},
                    "hostname": {"type": "string", "index": "not_analyzed"},
                    "timestamp": {"type": "date"},
                }
            }
        }

        shodan_port_mapping = {
            "shodan_port": {
                "properties": {
                    "ip_address": {"type": "string"},
                    "source": {"type": "string"},
                    "workspace": {"type": "string"},
                    "hostname": {"type": "string", "index": "not_analyzed"},
                    "port": {"type": "integer"},
                    "timestamp": {"type": "date"},
                }
            }
        }

        shodan_metadata_mapping = {
            "shodan_metadata": {
                "properties": {
                    "ip_address": {"type": "string"},
                    "source": {"type": "string"},
                    "workspace": {"type": "string"},
                    "hostname": {"type": "string", "index": "not_analyzed"},
                    "timestamp": {"type": "date"},
                }
            }
        }

        elastic.indices.create("bug_bounty")
        elastic.indices.put_mapping(index="bug_bounty", doc_type="host", body=host_mapping)
        elastic.indices.put_mapping(index="bug_bounty", doc_type="shodan_port", body=shodan_port_mapping)
        elastic.indices.put_mapping(index="bug_bounty", doc_type="shodan_metadata", body=shodan_metadata_mapping)

    except:
        traceback.print_exc()