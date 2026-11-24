# Lake Formation – 2. Permissions, LF-tags and fine-grained access

Short notes. Each point is a fact you can be asked about.

## A. The permission model in one picture
- Lake Formation permissions are **granted to principals on resources**. Think SQL: `GRANT SELECT ON table TO principal`.
- To do anything, a principal needs **both**:
  1. **IAM permission** (coarse): the IAM actions for the API (Glue, Lake Formation, Athena...).
  2. **Lake Formation permission** (fine): `SELECT`, `INSERT`, `DESCRIBE` and so on on the resource.
- **Lake Formation permissions are secondary to IAM.** If IAM denies, Lake Formation cannot rescue it. If IAM allows but Lake Formation has no grant, access is denied.
- Three ways to grant Lake Formation permissions:
  1. **Named resource method**: grant on a specific database/table/column by name.
  2. **LF-TBAC** (tag-based): grant on **LF-tag expressions**. Recommended at scale.
  3. **ABAC with IAM tags / session tags**: grant to principals that carry matching IAM tags (section H).
- You can combine methods. A principal's effective permission is the **union** of everything granted.
- **Grant option** (`WITH GRANT OPTION`): lets the grantee pass the same permission on to others. Without it they can use but not share.
- Data lake administrators can grant anything. Others can grant **only what they hold with the grant option**.
- Principals you can grant to: IAM user/role, SAML user/group, **IAM Identity Center** user/group, **Amazon Quick** user/group, **AWS account**, **organization**, **OU**, plus the special groups `IAMAllowedPrincipals` and `ALLIAMPrincipals`.
- CLI: `aws lakeformation grant-permissions` / `revoke-permissions` (and `batch-grant-permissions` / `batch-revoke-permissions` to reduce concurrency errors).

## B. Permissions per resource type
| Resource | Valid permissions |
|---|---|
| **Catalog** | ALL (Super), ALTER, CREATE_DATABASE, DESCRIBE, DROP, Super user |
| **Database** | ALL (Super), ALTER, CREATE_TABLE, DESCRIBE, DROP |
| **Table** | ALL (Super), ALTER, DELETE, DESCRIBE, DROP, INSERT, SELECT |
| **View** | ALL (Super), SELECT, DESCRIBE, DROP |
| **S3 data location** | DATA_LOCATION_ACCESS |
| **LF-tag** | DROP, ALTER (and CREATE LF-tag on the catalog) |
| **LF-tag values** | ASSOCIATE, DESCRIBE, grant with LF-tag expression |
| **Resource link** (db or table) | DESCRIBE, DROP |
| **Table with data filter** | DESCRIBE, DROP, SELECT |
| **Table with column filter** | SELECT |

## C. What each permission means
- **`SELECT`**: see the table in the Catalog and **query the data** in S3. If column filtering was set, only those columns are visible/queryable. **Engines apply the filtering.** Applies to **S3 data only** (not RDS and other stores).
- **`INSERT`**: insert, update and read data at the table's S3 location. Also lets you see the table.
- **`DELETE`**: same data access as INSERT (the docs describe both the same way) plus delete. S3 data only. **(verify delete vs insert wording)**
- **`DESCRIBE`**: **see that the table/database exists** and its metadata. **No data access**, and a user with only DESCRIBE on a database **cannot list its tables**. Implicitly granted when you hold any other permission on the resource. **You cannot grant DESCRIBE to someone with partial (column) SELECT**, and you cannot set column lists on a DESCRIBE grant.
- **`ALTER`**: change **metadata** (schema, parameters) of a database or table. Does **not** change the data in S3. If the altered property is a **registered location**, the principal needs **data location permission** on the new location.
- **`DROP`**: drop a database, table or resource link. **Dropping a database drops all its tables.** You **cannot grant DROP on a database to an external account**.
- **`CREATE_DATABASE`** (on the **catalog**): create a database or resource link in the Data Catalog. The creator gets `CREATE_TABLE`, `ALTER`, `DROP` on it (with grant option). **No** data permissions.
- **`CREATE_TABLE`** (on a **database**): create a table or resource link in that database. The creator gets **all** permissions on the table with grant option.
- **`DATA_LOCATION_ACCESS`** (on an **S3 location**): lets the principal **create or alter catalog entries that point to that registered location**. Applies to child locations too. **Not needed to query or write the data.**
- **`Super` / `ALL`**: every supported operation on the database or table. Can coexist with other grants. Revoking Super leaves the other grants. You **cannot grant Super on a database to an external account**.
- **`Super user`** (on a **catalog**, not the default catalog): can do everything on the databases and tables inside that catalog and can grant them. It **cannot** alter or drop the catalog itself.
- **`ASSOCIATE`** (on an **LF-tag**): attach that tag to Data Catalog resources. Implicitly gives DESCRIBE.
- **Each Lake Formation permission has IAM companions**. Examples: ALTER on a table also needs `glue:UpdateTable`; CREATE_TABLE needs `glue:CreateTable`; DROP table needs `glue:DeleteTable`; SELECT on a **registered** location needs **no extra S3 IAM** (the registration role handles S3) but needs `lakeformation:GetDataAccess`.

## D. Data location permissions (the creation rule)
- `DATA_LOCATION_ACCESS` decides who may **point a table or database at an S3 location**. It is an **extra safety layer**.
- Create-table rules:
  - Location **not registered** → `CREATE_TABLE` is enough.
  - Location **registered**, and the database has **no location** (or a different one) → `CREATE_TABLE` **plus** `DATA_LOCATION_ACCESS`.
  - Location **registered** and the database's location is a **registered parent prefix** of the table path → `CREATE_TABLE` alone is enough (implicit data location access).
- Create-database rules: no location → `CREATE_DATABASE`; unregistered location → `CREATE_DATABASE`; registered location → `CREATE_DATABASE` **plus** data location access.
- A grant of data location access on a path **covers child paths**.
- **Partition operations** (`CreatePartition`, `BatchCreatePartition`, `UpdatePartition`) do **not** need data location permission when the partition path is **under the table's registered location**.
- You do **not** need data location permission to **read or write** data. `SELECT`/`INSERT` is enough there.
- Cross-account: the owner account that registered the location must **grant data location access with the grant option** and, when granting later, you give the **catalog ID of the owner account**.
- Typical error: *"Insufficient Lake Formation permissions on <S3 location>"* → missing `DATA_LOCATION_ACCESS`.

## E. Column-level, row-level and cell-level security (data filters)
- Filters apply **only to reads**, so you can grant **only `SELECT`** with them.
- Three levels:
  - **Column-level**: show only chosen columns (include list or exclude list). Also for **nested (struct) columns**.
  - **Row-level**: show only rows matching a **row filter expression**.
  - **Cell-level**: **both** column and row filtering together (restrict a column only for some rows).
- A **data filter** (data cells filter) is a **named object on one table**: filter name, table, **column specification**, and **row filter expression** (or "all rows").
  - **All columns + row expression** → row-level only.
  - **Column list + all rows** → column-level only.
  - **Column list + row expression** → cell-level.
- Create a filter with `CreateDataCellsFilter` (or the console). You then **grant `SELECT` on the table "with data filter X"** to a principal.
- Example: filter `restrict-pharma` = exclude `customer_name`, row filter `product_type='pharma'`. Filter `no-pharma` = all columns, row filter `product_type<>'pharma'`.
- Who can create filters: someone with **`SELECT` with grant option** on the table. Data lake admins can by default.
- **Simple column filtering** (without a filter object): grant `SELECT` on a table with an **inclusion** or **exclusion** column list.
- **Row filter expression syntax** (PartiQL subset, like a `WHERE` clause):
  - Operators: `=, >, <, >=, <=, <>, !=, BETWEEN, IN, LIKE, NOT, IS [NOT] NULL`, combined with **AND/OR**.
  - Compare a **column to a constant**. You **cannot compare a column to another column**. **No functions** (user-defined or standard).
  - **String constants use single quotes.** String comparisons and `LIKE` are **case-sensitive**.
  - Supported types: STRING/CHAR/VARCHAR, INT/LONG/BIGINT/FLOAT/DECIMAL/DOUBLE, BOOLEAN, STRUCT. **Array and map are not supported** in row filters.
  - Expression length must be **under 2,048 characters**.
  - `IS [NOT] NULL` is **not allowed on partition columns**.
  - Reserved PartiQL words (for example `first`, `last`, `asc`, `missing`) as column names need **double quotes**.
  - Nested fields: use `customer.customerId`. Do not reference nested fields under partition columns.
- **Column filtering notes and limits**:
  - You **cannot apply column filtering on partition keys**.
  - Granting `SELECT` **with grant option** and column filtering → you must use an **include list**.
  - To grant `SELECT` with column filtering you must hold `SELECT` **with grant option and no row restrictions** (all rows).
  - A principal with `SELECT` on **some** columns **cannot** also hold `ALTER`, `DROP`, `DELETE`, `INSERT` on the table. If a principal has those, a column-filtered `SELECT` has **no effect**.
  - Nested column filtering: up to **5 levels** deep. Nested names with double quotes need doubled quotes (`"a"."b"."double""quote"`).
  - Column filtering is **inclusion-only in Athena and Redshift Spectrum for cross-account** use and is **not supported in Glue ETL** for that case (Glue 5.0+ adds fine-grained read, see file 3).
- **Cell-level filtering notes and limits**:
  - **Not supported** on nested columns, **views** and **resource links**.
  - No limit on the number of filters per table, but **max 100 data filters for one principal on a table**.
  - To apply a row expression you need `SELECT` with grant option on **all columns**.
  - **User + group** both granted row subsets → the principal gets the **union** of rows.
  - An **all-rows** filter **wins** over other row predicates held at the same time.
  - **External account**: the recipient admin's effective predicate is the **intersection** of the account-level predicate and any predicate given to the principal directly (for example `dept='hr'` AND `country='us'`).
  - `SELECT INTO` is not supported. Some column names are reserved (for example `ctid`, `oid`, `xmin`, `tableoid`).
  - Cell-level security is available in all Regions with **Athena engine v3** and **Redshift Spectrum**. Other services only in listed Regions.
- Filters give **security without copying data**. A copy-per-team approach is costly and goes stale.

## F. LF-tags and tag-based access control (LF-TBAC)
- **LF-tag** = a **key-value pair** such as `department=sales` or `classification=restricted`. A key can have **several allowed values** (`department=sales,marketing,finance`).
- **LF-TBAC** = grant permissions by **tag match**: attach tags to resources, grant tag expressions to principals. A principal gets access when **their granted tag values match the resource's tag values**.
- It is the **recommended** method when there are **many** databases, tables and columns. It scales: with `n(P)` principals and `n(R)` resources, named grants need `n(P) × n(R)`; LF-TBAC needs about `n(P) + n(R)`.
- **Workflow** (7 steps):
  1. Plan tags and relationships.
  2. Add **LF-tag creators** (optional delegation).
  3. **Create LF-tags**.
  4. **Assign LF-tags** to resources.
  5. Grant others the right to **assign** tags (ASSOCIATE), optionally with grant option.
  6. **Grant LF-tag expressions** to principals (with the data permissions, for example SELECT/INSERT on tables).
  7. After testing, **revoke the older named-resource grants**.
- **Who can create tags**: data lake admins and **LF-tag creators** (non-admins with the right). Creators can update/delete tags, assign tags and grant tag permissions.
- Two kinds of permissions on tags:
  - **LF-tag permissions**: `Create LF-Tag`, `Alter`, `Drop` (manage tag definitions).
  - **LF-tag value permissions**: `Associate` (assign), `Describe`, `Grant with LF-tag expression` (use tags to grant data permissions).
- **Inheritance**: **tables inherit tags from the database; columns inherit from the table.** You can **override** an inherited value on a lower level. Example: tag the database `module=Sales`, tag one table `module=Orders`.
- **No wildcards.** To tag all tables, tag the **database**. To tag all columns, tag the **table**.
- **How tags combine** (important for the exam):
  - A grant with **several tag keys** → the resource must have **all** of them (**AND** across keys).
  - A grant with **several values for one key** → resource may have **any** of them (**OR** across values of a key).
  - Expression example: `module=sales AND division=(consumer OR commercial)`.
  - To get "A **or** B" across different keys, make **two separate grants**.
  - A resource can have **only one value per key** (`module=Orders` or `module=Customers`, not both).
- **Rules and limits**:
  - **Define tags before** assigning or granting them. You **cannot assign tags while creating** a resource, only after it exists.
  - **Key and value length** max **50 characters**. Keys and values are stored in **lower case**.
  - Max **50 LF-tags per resource**.
  - Soft limits: **10,000 LF-tags** per account, **1,000 values** per tag.
  - **Saved LF-tag expressions**: up to **1,000** per account; up to **50** expressions in one grant to a principal. An **inline** expression in a grant/revoke must be **900 bytes or less** (use a saved expression for bigger).
  - If a tag match covers only **some columns** and the granted permission needs full-column access (`ALTER`, `DROP`, `INSERT`, `DELETE`), **none of those is given**. Only `DESCRIBE` (and for `Super`, `SELECT` and `DESCRIBE`).
  - Tag-granting rights: a holder of **Grant with LF-tag expression** can grant data permissions by named resource, or by tags **only with the same full expression**.
  - Named + tag grants on the same resource → **union** of permissions.
  - Tags created in one account can be used only on that account's resources. You **cannot tag a shared resource** from another account with your own tags.
- **IAM tags are not LF-tags.** They are different and not interchangeable. IAM tags control IAM policies. LF-tags control Lake Formation permissions.
- **Lake Formation is still secondary to IAM** even with matching tags.
- **Redshift federated catalogs created before the LF-tag release** need AWS Support to add LF-tags **(from the docs)**.

## G. Metadata vs data permissions (two kinds)
- **Metadata permissions**: `CREATE_DATABASE`, `CREATE_TABLE`, `ALTER`, `DROP`, `DESCRIBE`. Control the **catalog objects**.
- **Data permissions**: `SELECT`, `INSERT`, `DELETE` (S3 data) and `DATA_LOCATION_ACCESS` (pointing to storage).
- Creating a database gives **metadata** permissions only. Creating a table gives **all table permissions** to the creator (with grant option).
- Permission to **query** is not permission to **alter the schema** and vice versa.

## H. ABAC with IAM tags and session tags
- **Attribute-based access control (ABAC)** in Lake Formation: grant on catalog objects (catalogs, databases, tables, **data filters**) to **any IAM principal whose IAM tag or session tag matches** the key/value.
- Works in the **same account and cross-account**. You need **grantable permissions** on the resource to make these grants.
- New users get access **automatically by attribute** (department, job role) without new grants.
- Difference to LF-TBAC: **LF-tags** label **data resources**; **ABAC** matches **principal IAM/session tags**. LF-TBAC works with IAM ABAC: IAM gives broad access, LF-TBAC narrows it **(verify exact grant syntax and Regions)**.
- Prefer LF-TBAC for large catalogs. Use ABAC when identity attributes (federated session tags) already exist.

## I. IAM Identity Center and federated users
- You can grant Lake Formation permissions to **IAM Identity Center users and groups** (principal ARNs like `arn:aws:identitystore:::user/<id>`).
- **SAML** users and groups: principal `arn:aws:iam::<account>:saml-provider/<name>:user/<user>` or `:group/<group>`.
- With the registration role trust policy including `sts:SetContext`, **Identity Center user context** appears in CloudTrail logs.
- **Trusted identity propagation** passes the real user to the analytics service so Lake Formation checks **that user** (not just the role) **(verify)**.

## J. Common mistakes and traps
- Granting `SELECT` only in Lake Formation and **forgetting `lakeformation:GetDataAccess` in IAM**.
- Leaving **`IAMAllowedPrincipals`** on the table, so Lake Formation is **not** enforced.
- Using **exclusion** column lists with **grant option** (not allowed). Use inclusion lists.
- Granting DESCRIBE to someone with **partial SELECT** (not allowed).
- Expecting `DATA_LOCATION_ACCESS` to allow **reading** data (it does not).
- Using **partition keys** in column filters (not allowed).
- Assuming a **group** grant replaces a user grant (they **add up**).
- Giving tag **expressions across keys** expecting OR (it is AND).
- Forgetting that **dropping a database drops its tables** and DROP cannot go to external accounts.
- Using **resource links** to share access (links do **not** carry permission to the target).
- Granting **ALTER/INSERT/DELETE** to a principal who also has column-filtered `SELECT`.
- **Concurrent grants** can throw `ConcurrentModificationException`. Retry, or use the **batch** APIs.

## K. Scenarios (if → then, because)
- If 200 tables must be accessible by finance but only non-PII columns → tag columns `pii=false` and grant `pii=false` to finance, because tags scale and inherit.
- If one table must show different rows per region manager → **row-level data filters** (`region='west'`) per group, because it avoids copying.
- If a column must be hidden only for some rows → **cell-level filter**, because it combines row and column rules.
- If a new table is added and should be visible to the same teams → tag it (or its database), because tag grants apply automatically.
- If a user needs access to sales **or** marketing data → two separate tag grants (or one key with both values), because different keys combine with AND.
- If you grant `module=sales AND region=west` and a table has only `module=sales` → no access, because **all** granted keys must match.
- If an analyst can query but cannot see any tables in the list → missing `DESCRIBE` (implied by other grants) or IAM Glue read actions, because the catalog hides them.
- If a data engineer can create a table in the database but gets an S3 location error → add **`DATA_LOCATION_ACCESS`** on that path, because the path is registered.
- If a job role needs to read a table but not change it → `SELECT` only, because `INSERT` and `DELETE` allow changes.
- If an analyst must not be able to share data onward → grant **without the grant option**.
- If a principal has both a named grant and a tag grant → effective access is the **union**.
- If a granted column-filtered user also receives `INSERT` → the filter stops applying, because full access wins. Do not mix.
- If federated users come from an IdP with department attributes → **ABAC with session tags** or LF-TBAC with IAM Identity Center groups.
- If you want to remove old named grants after switching to tags → test tag access first, then revoke named grants (step 7 of the LF-TBAC workflow).
- If many grants fail with ConcurrentModificationException → retry, or use **BatchGrantPermissions**.

## Verified from AWS docs on 2026-10-20
Read from current AWS pages: permissions reference (resources, permissions, principals, Super, IAMAllowedPrincipals, DESCRIBE/SELECT/CREATE_TABLE/DATA_LOCATION_ACCESS rules), underlying data access control and data location rules, LF-TBAC overview and best practices (limits, inheritance, combination rules), LF-tag management, data filtering and its limitations, PartiQL row filter syntax, attribute-based access control overview.
Not confirmed (verify): DELETE vs INSERT wording, ABAC grant syntax and Region list, trusted identity propagation details, whether the 10,000 tags / 1,000 values soft limits are adjustable in your Region, exact set of Regions for cell-level security outside Athena v3 and Redshift Spectrum.
