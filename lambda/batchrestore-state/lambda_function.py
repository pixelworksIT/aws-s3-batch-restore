## #!/usr/bin/env python3
##
# Copyright 2019 Pixelworks Inc.
#
# Author: Houyu Li <hyli@pixelworks.com>
#
# Query restore status for a specific request
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
    # We need batchId in input
    batch_id = None
    if u'batchId' in event:
        batch_id = event[u'batchId'].strip()
    if not batch_id:
        return _ret(500, u"Empty restore request ID.")

    # The AWS session
    aws_sess = boto3.session.Session(
        region_name = os.environ[u'AWS_REGION'],
        aws_access_key_id = os.environ[u'AWS_ACCESS_KEY_ID'],
        aws_secret_access_key = os.environ[u'AWS_SECRET_ACCESS_KEY'],
        aws_session_token = os.environ[u'AWS_SESSION_TOKEN']
    )

    # DynamoDb tables
    tbl_batch_restore_objects = aws_sess.resource(u'dynamodb').Table(u'BatchRestoreObjects')

    # Number of unfinished object restore
    n_unfinished = 0
    # Number of finished object restore
    n_finished = 0

    res_objs = {}
    try:
        # Get all objects
        res_objs = tbl_batch_restore_objects.query(
            IndexName = u'batchId-index',
            KeyConditions = {
                u'batchId' : {
                    u'AttributeValueList' : [
                        batch_id
                    ],
                    u'ComparisonOperator' : u'EQ'
                }
            }
        )
    except:
        # Query error. Set 0 to Count
        res_objs[u'Count'] = 0

    if res_objs[u'Count'] > 0:
        # Found restoring object
        for obj in res_objs[u'Items']:
            # Record number of each state
            if u'state' not in obj:
                n_unfinished += 1
            else:
                if obj[u'state'] == u'Done':
                    n_finished += 1
                else:
                    n_unfinished += 1

        ret_data = _ret(200, u"Objects state checked")
        ret_data[u'body'][u'finished'] = n_finished
        ret_data[u'body'][u'ongoing'] = n_unfinished
        return ret_data
    else:
        # Not found any object?
        return _ret(404, u"No object in provided request %s" % (batch_id))

def _ret(code, message):
    return {
        u'statusCode': code,
        u'body': {
            u'message': message
        }
    }
