-- Only for the separate v2_upgrade_test database at migration 0016.
INSERT INTO knowledge_spaces(id,name,visibility) VALUES('10000000-0000-0000-0000-000000000001','synthetic legacy space','PUBLIC');
INSERT INTO categories(id,space_id,name,is_open) VALUES
('10000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000001','legacy open',true),
('10000000-0000-0000-0000-000000000007','10000000-0000-0000-0000-000000000001','legacy second',true);
INSERT INTO documents(id,space_id,category_id,original_filename,storage_key,mime_type,size_bytes,sha256,status)
VALUES('10000000-0000-0000-0000-000000000003','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000002','legacy.txt','synthetic/legacy.txt','text/plain',12,repeat('a',64),'READY');
INSERT INTO document_versions(id,document_id,version_number,parser_version,embedding_provider,embedding_model,embedding_dimension,chunk_config,status)
VALUES('10000000-0000-0000-0000-000000000004','10000000-0000-0000-0000-000000000003',1,'legacy','bge','synthetic',1024,'{}','READY'),
('10000000-0000-0000-0000-000000000005','10000000-0000-0000-0000-000000000003',2,'legacy','bge','synthetic',1024,'{}','READY');
UPDATE documents SET active_version_id='10000000-0000-0000-0000-000000000005';
INSERT INTO chunks(id,document_id,document_version_id,space_id,category_id,ordinal,heading_path,content,content_hash,token_count,embedding,is_active)
VALUES('10000000-0000-0000-0000-000000000006','10000000-0000-0000-0000-000000000003','10000000-0000-0000-0000-000000000005','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000002',1,'[]','synthetic legacy',repeat('b',64),3,(ARRAY[1.0] || array_fill(0.0,ARRAY[1023]))::vector,true);
