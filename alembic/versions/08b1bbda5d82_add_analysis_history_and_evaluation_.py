"""Add analysis history and evaluation tables

Revision ID: 08b1bbda5d82
Revises: 
Create Date: 2026-01-19 11:07:39.273514

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '08b1bbda5d82'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - Add new evaluation tables and update analysis_history."""
    # Create new tables
    op.create_table('admin_metrics',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('metric_date', sa.Date(), nullable=False),
    sa.Column('total_queries', sa.Integer(), nullable=True),
    sa.Column('avg_precision', sa.Float(), nullable=True),
    sa.Column('avg_latency_ms', sa.Float(), nullable=True),
    sa.Column('cache_hit_rate', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('metric_date')
    )
    op.create_table('evaluation_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('run_name', sa.String(length=255), nullable=False),
    sa.Column('run_type', sa.String(length=50), nullable=True),
    sa.Column('total_queries', sa.Integer(), nullable=True),
    sa.Column('avg_precision_at_5', sa.Float(), nullable=True),
    sa.Column('avg_hallucination_rate', sa.Float(), nullable=True),
    sa.Column('avg_integration_feasibility', sa.Float(), nullable=True),
    sa.Column('avg_latency_ms', sa.Float(), nullable=True),
    sa.Column('config_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('evaluation_query_results',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=False),
    sa.Column('scenario_name', sa.String(length=255), nullable=True),
    sa.Column('query', sa.Text(), nullable=False),
    sa.Column('expected_tools', sa.ARRAY(sa.Text()), nullable=True),
    sa.Column('retrieved_tools', sa.ARRAY(sa.Text()), nullable=True),
    sa.Column('precision_at_5', sa.Float(), nullable=True),
    sa.Column('hallucination_detected', sa.Boolean(), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['run_id'], ['evaluation_runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    
    # Update analysis_history table with new columns
    op.add_column('analysis_history', sa.Column('user_id', sa.String(length=255), nullable=True))
    op.add_column('analysis_history', sa.Column('intent_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('analysis_history', sa.Column('tool_stack_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('analysis_history', sa.Column('roadmap_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('analysis_history', sa.Column('has_hallucination', sa.Boolean(), nullable=True))
    
    # Note: Keeping existing tables (tools, tool_embeddings, user_feedback) intact


def downgrade() -> None:
    """Downgrade schema - Remove new tables and columns."""
    # Remove new columns from analysis_history
    op.drop_column('analysis_history', 'has_hallucination')
    op.drop_column('analysis_history', 'roadmap_json')
    op.drop_column('analysis_history', 'tool_stack_json')
    op.drop_column('analysis_history', 'intent_json')
    op.drop_column('analysis_history', 'user_id')
    
    # Drop new tables
    op.drop_table('evaluation_query_results')
    op.drop_table('evaluation_runs')
    op.drop_table('admin_metrics')
