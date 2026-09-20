# The network (docs/design/infrastructure.md §6, "The network"), and the whole of REQ-018: there
# is no internet gateway and no NAT gateway in this file, so nothing in the VPC has a route out.
# The only traffic that leaves the app subnets is PostgreSQL to the database and HTTPS to S3
# through the gateway endpoint, which stays on AWS's network. Lambda does the invoking, the queue
# polling, the image pulling and the log shipping from outside the VPC (ADR-0003), which is why
# no interface endpoint — at USD 7 a month each — is needed either.

resource "aws_vpc" "this" {
  #checkov:skip=CKV2_AWS_11:flow logs would record traffic that can't leave the VPC (REQ-018), and their ingestion is a cost this budget doesn't carry (ADR-0003)
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags                 = { Name = local.prefix }
}

# The VPC's own default security group belongs to nothing and allows nothing: every resource here
# names the security group it uses.
resource "aws_default_security_group" "this" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${local.prefix}-default-unused" }
}

resource "aws_subnet" "app" {
  count             = length(var.app_subnet_cidrs)
  vpc_id            = aws_vpc.this.id
  cidr_block        = var.app_subnet_cidrs[count.index]
  availability_zone = local.zones[count.index]
  tags              = { Name = "${local.prefix}-app-${local.zones[count.index]}" }
}

resource "aws_subnet" "db" {
  count             = length(var.db_subnet_cidrs)
  vpc_id            = aws_vpc.this.id
  cidr_block        = var.db_subnet_cidrs[count.index]
  availability_zone = local.zones[count.index]
  tags              = { Name = "${local.prefix}-db-${local.zones[count.index]}" }
}

# Two route tables, neither with a 0.0.0.0/0 route. The app one carries the S3 gateway endpoint;
# the database needs nothing beyond the VPC's local route.
resource "aws_route_table" "app" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${local.prefix}-app" }
}

resource "aws_route_table" "db" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${local.prefix}-db" }
}

resource "aws_route_table_association" "app" {
  count          = length(aws_subnet.app)
  subnet_id      = aws_subnet.app[count.index].id
  route_table_id = aws_route_table.app.id
}

resource "aws_route_table_association" "db" {
  count          = length(aws_subnet.db)
  subnet_id      = aws_subnet.db[count.index].id
  route_table_id = aws_route_table.db.id
}

# S3, reached without leaving AWS's network and without an hourly charge. A gateway endpoint is a
# route, not an address, so it appears in the app route table.
resource "aws_vpc_endpoint" "s3" {
  # Its prefix list is what the fn security group allows HTTPS to: S3's own addresses, kept
  # current by AWS.
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${data.aws_region.current.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.app.id]
  tags              = { Name = "${local.prefix}-s3" }
}

# The functions' security group. It is what the egress rules say it is: PostgreSQL to the
# database, and HTTPS to S3's own addresses.
resource "aws_security_group" "fn" {
  #checkov:skip=CKV2_AWS_5:the four functions attach it in T020; its rules are what they may reach
  name        = "${local.prefix}-fn"
  description = "${local.prefix}: the functions. Out to the database and to S3 only; nothing in."
  vpc_id      = aws_vpc.this.id
  tags        = { Name = "${local.prefix}-fn" }
}

resource "aws_vpc_security_group_egress_rule" "fn_to_db" {
  security_group_id            = aws_security_group.fn.id
  description                  = "PostgreSQL to the database"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = aws_security_group.db.id
}

resource "aws_vpc_security_group_egress_rule" "fn_to_s3" {
  security_group_id = aws_security_group.fn.id
  description       = "HTTPS to S3 through the gateway endpoint"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  prefix_list_id    = aws_vpc_endpoint.s3.prefix_list_id
}

# The database's. It accepts PostgreSQL from the functions and nothing else, and has no egress
# rule at all: Terraform removes the allow-all one AWS adds.
resource "aws_security_group" "db" {
  name        = "${local.prefix}-db"
  description = "${local.prefix}: the database. PostgreSQL from the functions only; nothing out."
  vpc_id      = aws_vpc.this.id
  tags        = { Name = "${local.prefix}-db" }
}

resource "aws_vpc_security_group_ingress_rule" "db_from_fn" {
  security_group_id            = aws_security_group.db.id
  description                  = "PostgreSQL from the functions"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = aws_security_group.fn.id
}
