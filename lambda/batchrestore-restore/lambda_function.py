## #!/usr/bin/env python3
##
# Copyright 2019 Pixelworks Inc.
#
# Author: Houyu Li <hyli@pixelworks.com>
#
# Send object restore request based on data from DynamoDB Stream
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# 		http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
## // ##

import os, json
import boto3

def lambda_handler(event, context):
    # The AWS session
    aws_sess = boto3.session.Session(
        region_name = os.environ[u'AWS_REGION'],
        aws_access_key_id = os.environ[u'AWS_ACCESS_KEY_ID'],
        aws_secret_access_key = os.environ[u'AWS_SECRET_ACCESS_KEY'],
        aws_session_token = os.environ[u'AWS_SESSION_TOKEN']
    )

    # The S3 client
    s3_client = aws_sess.client(u's3')
    # DynamoDb tables
    tbl_app_config = aws_sess.resource(u'dynamodb').Table(u'AppConfig')

    # Loop throw all records
    for record in event[u'Records']:
        if record[u'eventName'] == u'INSERT':
            # We only care about new records
            # Try to send restore request
            try:
                s3_client.restore_object(
                    Bucket = record[u'dynamodb'][u'NewImage'][u'bucket'][u'S'],
                    Key = record[u'dynamodb'][u'NewImage'][u'key'][u'S'],
                    RestoreRequest = {
                        u'Days': int(_get_appconfig(tbl_app_config, u'batch-restore-active-days')),
                        u'GlacierJobParameters': { u'Tier': u'Standard' }
                    }
                )
                print(u"Restore request sent: s3://%s/%s" % (
                    record[u'dynamodb'][u'NewImage'][u'bucket'][u'S'],
                    record[u'dynamodb'][u'NewImage'][u'key'][u'S']))
            except:
                # We ignore all errors
                # Just print a log
                print(u"Restore request failed: s3://%s/%s" % (
                    record[u'dynamodb'][u'NewImage'][u'bucket'][u'S'],
                    record[u'dynamodb'][u'NewImage'][u'key'][u'S']))

    # Return true anyway. Let the monitor function to decide actual state of retore.
    return {
        u'statusCode': 200,
        u'body': {
            u'message': u"Return success anyway."
        }
    }

def _get_appconfig(table, conf_key):
    return table.get_item(
        Key = {
            u'confKey': conf_key
        },
        ConsistentRead = True
    )[u'Item'][u'confValue']