# Test images

Dropbox for sample frames used by `../test_perceptron.py` (and any future adapter
iteration scripts). Files in this folder are gitignored — they're personal scratch data.

## Pulling a sample from the live S3 bucket

Storage backend on prod is DigitalOcean Spaces. Use the running backend container to
generate a presigned URL, then curl it locally:

```bash
ssh root@45.55.232.164 'docker exec hive-backend python -c "
import boto3, os
client = boto3.client(\"s3\",
    endpoint_url=os.environ[\"S3_ENDPOINT_URL\"],
    aws_access_key_id=os.environ[\"S3_ACCESS_KEY_ID\"],
    aws_secret_access_key=os.environ[\"S3_SECRET_ACCESS_KEY\"],
    region_name=os.environ[\"S3_REGION\"])
print(client.generate_presigned_url(\"get_object\",
    Params={\"Bucket\": os.environ[\"S3_BUCKET\"], \"Key\": \"<SAMPLE_IMAGE_PATH>\"},
    ExpiresIn=600))
"'
```

Find `<SAMPLE_IMAGE_PATH>` with:

```bash
ssh root@45.55.232.164 'docker exec hive-postgres psql -U hive -d hive -tAc \
  "SELECT image_path FROM samples WHERE source_role = '\''classification_channel'\'' \
   ORDER BY uploaded_at DESC LIMIT 5"'
```

Save as `c4_<n>.jpg` (or `cc_<n>.jpg` for chamber, etc.) so the convention stays obvious.
