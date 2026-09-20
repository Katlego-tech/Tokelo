# The network (docs/design/infrastructure.md §6, "The network"), and the whole of REQ-018: there
# is no internet gateway and no NAT gateway in this file, so nothing in the VPC has a route out.
# The only traffic that leaves the app subnets is PostgreSQL to the database and HTTPS to S3
# through the gateway endpoint, which stays on AWS's network. Lambda does the invoking, the queue
# polling, the image pulling and the log shipping from outside the VPC (ADR-0003), which is why
# no interface endpoint — at USD 7 a month each — is needed either. S3 and DynamoDB are reached
# through gateway endpoints, which are routes on AWS's own network (ADR-0011).

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

# One route table, with no 0.0.0.0/0 route: the VPC's local route, and the two gateway endpoints.
resource "aws_route_table" "app" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${local.prefix}-app" }
}

resource "aws_route_table_association" "app" {
  count          = length(aws_subnet.app)
  subnet_id      = aws_subnet.app[count.index].id
  route_table_id = aws_route_table.app.id
}

# S3 and DynamoDB, reached without leaving AWS's network and without an hourly charge. A gateway
# endpoint is a route, not an address, so each appears in the app route table. Each one's prefix
# list is what the fn security group allows HTTPS to: that service's own addresses, kept current
# by AWS.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${data.aws_region.current.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.app.id]
  tags              = { Name = "${local.prefix}-s3" }
}

# The policy is the second lock on the store: even with a role that allowed more, nothing can
# reach a table of another project's or another environment's through this route (REQ-018).
resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${data.aws_region.current.region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.app.id]
  policy            = data.aws_iam_policy_document.dynamodb_endpoint.json
  tags              = { Name = "${local.prefix}-dynamodb" }
}

data "aws_iam_policy_document" "dynamodb_endpoint" {
  #checkov:skip=CKV_AWS_283:an endpoint policy says what may pass through this route, not who may call: the principal is every caller in the VPC, and the two tables named below are all it reaches
  statement {
    principals {
      type        = "AWS"
      identifiers = ["*"] # narrowed by the resources below, and by each function's own role
    }
    actions   = ["dynamodb:*"]
    resources = [aws_dynamodb_table.main.arn, aws_dynamodb_table.audit.arn]
  }
}

# The functions' security group. It is what the egress rules say it is: HTTPS to S3's and
# DynamoDB's own addresses, and nothing else — no inbound rule at all.
resource "aws_security_group" "fn" {
  #checkov:skip=CKV2_AWS_5:the four functions attach it in T020; its rules are what they may reach
  name        = "${local.prefix}-fn"
  description = "${local.prefix}: the functions. Out to the database and to S3 only; nothing in."
  vpc_id      = aws_vpc.this.id
  tags        = { Name = "${local.prefix}-fn" }
}

resource "aws_vpc_security_group_egress_rule" "fn_to_s3" {
  security_group_id = aws_security_group.fn.id
  description       = "HTTPS to S3 through the gateway endpoint"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  prefix_list_id    = aws_vpc_endpoint.s3.prefix_list_id
}

resource "aws_vpc_security_group_egress_rule" "fn_to_dynamodb" {
  security_group_id = aws_security_group.fn.id
  description       = "HTTPS to DynamoDB through the gateway endpoint"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  prefix_list_id    = aws_vpc_endpoint.dynamodb.prefix_list_id
}
