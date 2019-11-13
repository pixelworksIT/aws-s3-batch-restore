# S3 Batch Restore

This tool is for restoring archived objects in a given S3 bucket and prefix with one function call.

## Deploy

It's recommended to deploy this application in the same region as the S3 bucket you want to work on.

### Prepare Assets

#### Need an S3 Bucket

Prepare an S3 bucket. Make sure objects in it are accessible for the account which you are using to create the CloudFormation stack.

We will refer to this bucket as `my_bucket` in this document

#### Lambda packages

Clone this repository, then run following in BASH shell

```bash

cd aws-s3-batch-restore
mkdir -p BatchRestore/lambda
cd lambda
for func in $(ls .); do cd "$func"; zip -g "../../BatchRestore/lambda/""$func"".zip" "lambda_function.py"; cd ..; done
cd ..

```

You will have following packages ready in the repository folder.

```plaintext

...
./BatchRestore
./BatchRestore/lambda
./BatchRestore/lambda/batchrestore-request.zip
./BatchRestore/lambda/batchrestore-monitor.zip
./BatchRestore/lambda/batchrestore-state.zip
./BatchRestore/lambda/batchrestore-restore.zip
...

```

Upload the whole folder `./BatchRestore` to the root of `my_bucket` , so that paths of these Lambda packages will look like following in `my_bucket`.

```plaintext

s3://my_bucket/BatchRestore/lambda/******.zip

```

### Create the CloudFormation Stack

It's simple. Go to CloudFormation web console. Click "Create Stack". Follow the instruction. The template file is `cf-template.json`. When it asks input for `AssetsBucket`, please input the acture bucket name of `my_bucket`.

### Some Default Configuration Items in DynamoDB Table `AppConfig`

You need to add following items to DynamoDB table `AppConfig` to make this application working.

| **confKey** | **confValue** | **Notes** |
| ----------- | ------------- | -------------------------- |
| ses-smtp-server            | *String* | E-mail server hostname or address, running SMTP service. |
| ses-smtp-port              | *Number* | The SMTP service port. |
| ses-smtp-user              | *String* | Username to access the SMTP service. |
| ses-smtp-pass              | *String* | Password above user to access the SMTP service. |
| batch-restore-watchers     | *String* | E-mail addresses that will recieve restore finish notification mail. Seperated by comma (,). |
| batch-restore-monitor-func | *String* | ARN of Lambda function `batchrestoreMonitor`, which was created in CloudFormation stack. |
| batch-restore-active-days  | *Number* | How many days, after restored, the objects will stay active. |

Usage
------

### Function: batchrestoreRequest()

This function is used to make a restore request for a specific S3 bucket and prefix.

#### Input

```plaintext

{
    "bucket": "string",
    "prefix": "string",
    "watchers": "string"
}

```

> **bucket** (string) : **REQUIRED**
>
>> The bucket name. The bucket should be in the same region as the Lambda function.
>
>**prefix** (string) :
>
>> Prefix is path in the given bucket to search for archived objects. Prefix is without leading slash "/".
>
>**watcher** (string) :
>
>> E-mail addresses, separated by comma, that will receive restore finish notification E-mail.
>

#### Response

```plaintext

{
  "statusCode": number,
  "body": {
    "message": "string",
    "restoreCount": number,
    "batchId": "string",
    "restoreMonitor": "string"
  }
}

```

>**statusCode** (number) :
>
>> **200** indicates a successful request. Otherwise, see `body.message` for failure reason.
>
>**body.message** (string) :
>
>> Generally, telling about what happened about the request.
>
>**body.restoreCount** (number) :
>
>> The number of objects will be restored in the given bucket and prefix
>
>**body.batchId** (string) :
>
>> The ID for the restore request. Need this to invoke function `batchrestoreState()` for checking restore state.
>
>**body.restoreMonitor** (string) :
>
>> The name of the CloudWatch Event Rule for monitoring restore status. If it's empty, then contact [Support]
>

#### Example

```plaintext

import json, boto3

lambda_client = boto3.client('lambda')

payload = {
    'bucket': 'abc',
    'prefix': 'def/',
    'watchers': 'abc@example.com,def@example.com'
}

result = lambda_client.invoke(
    FunctionName = 'batchrestoreRequest',
    Payload = json.dumps(payload)
)

print(result['Payload'].read().decode())

```

### Function: batchrestoreState()

This function is used to query state of a restore request.

#### Input

```plaintext

{
    "batchId": "string"
}

```

> **batchId** (string) : **REQUIRED**
>
>> The restore request ID you get from response of function `batchrestoreRequest()`.
>

#### Response

```plaintext

{
  "statusCode": number,
  "body": {
    "message": "string",
    "finished": number,
    "ongoing": number
  }
}

```

>**statusCode** (number) :
>
>> **200** indicates a successful query. Otherwise, see `body.message` for failure reason.
>
>**body.message** (string) :
>
>> Generally, telling about what happened about the query.
>
>**body.finished** (number) :
>
>> On successful query, the number of objects have been restored.
>
>**body.ongoing** (number) :
>
>> On successful query, the number of objects is being restored.
>

#### Example

```plaintext

import json, boto3

lambda_client = boto3.client('lambda')

payload = {
    'batch_id': 'abc'
}

result = lambda_client.invoke(
    FunctionName = 'batchrestoreState',
    Payload = json.dumps(payload)
)

print(result['Payload'].read().decode())

```
