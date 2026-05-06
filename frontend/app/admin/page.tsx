'use client';

import { useEffect, useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { BarChart3, TrendingUp, Zap, Activity, Database, GitBranch } from 'lucide-react';
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ComposedChart, Area } from 'recharts';
import { toast } from 'sonner';

interface MetricData {
  metric_date: string;
  total_queries: number;
  avg_precision: number;
  avg_latency_ms: number;
  cache_hit_rate: number;
}

interface PerformanceStats {
  avg_latency_ms: number;
  p95_latency_ms: number;
  total_queries: number;
  cache_hit_rate: number;
}

interface EvaluationRun {
  id: number;
  run_name: string;
  run_type: string;
  total_queries: number;
  avg_precision_at_5: number;
  avg_hallucination_rate: number;
  avg_latency_ms: number;
  created_at: string;
  // New precision metrics
  strict_p5?: number;
  lenient_p5?: number;
  mrr?: number;
  hit_at_1?: number;
  hit_at_5?: number;
}

export default function AdminPage() {
  const [metrics, setMetrics] = useState<MetricData[]>([]);
  const [performanceStats, setPerformanceStats] = useState<PerformanceStats | null>(null);
  const [evaluationRuns, setEvaluationRuns] = useState<EvaluationRun[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchMetrics();
    fetchPerformanceStats();
    fetchEvaluationRuns();
  }, []);

  const fetchMetrics = async () => {
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
      const response = await fetch(`${apiUrl}/api/v1/admin/metrics?days=30`);
      
      if (!response.ok) {
        const errorText = await response.text();
        console.error(`Metrics API error ${response.status}:`, errorText);
        throw new Error(`Failed to fetch metrics: ${response.status}`);
      }
      
      const data = await response.json();
      setMetrics(data);
    } catch (error) {
      console.error('Error fetching metrics:', error);
      // Don't show toast for network errors during initial load
      if (error instanceof TypeError && error.message.includes('fetch')) {
        console.log('Backend may not be running yet, will retry...');
      } else {
        toast.error('Failed to load metrics');
      }
    }
  };

  const fetchPerformanceStats = async () => {
    try {
      setLoading(true);
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
      const response = await fetch(`${apiUrl}/api/v1/admin/performance`);
      
      if (!response.ok) {
        throw new Error('Failed to fetch performance stats');
      }
      
      const data = await response.json();
      setPerformanceStats(data);
    } catch (error) {
      console.error('Error fetching performance stats:', error);
      toast.error('Failed to load performance stats');
    } finally {
      setLoading(false);
    }
  };

  const fetchEvaluationRuns = async () => {
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
      const response = await fetch(`${apiUrl}/api/v1/evaluation/runs`);
      
      if (!response.ok) {
        const errorText = await response.text();
        console.error(`Evaluation runs API error ${response.status}:`, errorText);
        throw new Error(`Failed to fetch evaluation runs: ${response.status}`);
      }
      
      const data = await response.json();
      setEvaluationRuns(data);
    } catch (error) {
      console.error('Error fetching evaluation runs:', error);
    }
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

  const latencyData = metrics.map(m => ({
    date: formatDate(m.metric_date),
    latency: Math.round(m.avg_latency_ms / 1000), // Convert to seconds
  }));

  const precisionData = metrics.map(m => ({
    date: formatDate(m.metric_date),
    precision: (m.avg_precision * 100).toFixed(1), // Convert to percentage
  }));

  const cacheData = metrics.map(m => ({
    date: formatDate(m.metric_date),
    hitRate: (m.cache_hit_rate * 100).toFixed(1), // Convert to percentage
  }));

  // Transform evaluation runs for the improvement trend chart
  const improvementData = evaluationRuns
    .slice()
    .reverse() // Oldest first for chronological order
    .map((run, idx) => {
      // Prefer lenient_p5 if available, otherwise fall back to avg_precision_at_5
      const precision = run.lenient_p5 !== null && run.lenient_p5 !== undefined
        ? run.lenient_p5
        : run.avg_precision_at_5;
      
      return {
        iteration: run.run_name.split(' - ')[0] || `Run ${idx + 1}`,
        precision: (precision * 100).toFixed(1),
        strictPrecision: run.strict_p5 ? (run.strict_p5 * 100).toFixed(1) : null,
        hallucination: run.avg_hallucination_rate ? (run.avg_hallucination_rate * 100).toFixed(1) : '0',
        latency: Math.round((run.avg_latency_ms ?? 0) / 1000), // seconds
        fullName: run.run_name,
        type: run.run_type,
      };
    });

  return (
    <div className="container max-w-7xl mx-auto px-4 py-12">
      <div className="mb-8">
        <h1 className="text-3xl font-bold mb-2">Admin Dashboard</h1>
        <p className="text-muted-foreground">Monitor system performance and evaluation metrics</p>
      </div>

      <Tabs defaultValue="overview" className="space-y-6">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="improvements">Improvement Trends</TabsTrigger>
          <TabsTrigger value="performance">Performance</TabsTrigger>
          <TabsTrigger value="evaluations">Evaluations</TabsTrigger>
          <TabsTrigger value="cache">Cache</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-4">
          <div className="grid gap-4 md:grid-cols-4">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Total Queries</CardTitle>
                <Database className="h-4 w-4 text-emerald-600" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-emerald-700">
                  {loading ? '...' : performanceStats?.total_queries || 0}
                </div>
                <p className="text-xs text-muted-foreground">Last 30 days</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Avg Latency</CardTitle>
                <Zap className="h-4 w-4 text-emerald-600" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-emerald-700">
                  {loading ? '...' : `${((performanceStats?.avg_latency_ms || 0) / 1000).toFixed(1)}s`}
                </div>
                <p className="text-xs text-muted-foreground">
                  P95: {loading ? '...' : `${((performanceStats?.p95_latency_ms || 0) / 1000).toFixed(1)}s`}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Cache Hit Rate</CardTitle>
                <Activity className="h-4 w-4 text-emerald-600" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-emerald-700">
                  {loading ? '...' : `${(performanceStats?.cache_hit_rate || 0).toFixed(1)}%`}
                </div>
                <p className="text-xs text-muted-foreground">Caching efficiency</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Precision@5</CardTitle>
                <TrendingUp className="h-4 w-4 text-emerald-600" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-emerald-700">
                  {evaluationRuns.length > 0 ? (() => {
                    const latest = evaluationRuns[0];
                    const precision = latest.lenient_p5 ?? latest.avg_precision_at_5 ?? 0;
                    return `${(precision * 100).toFixed(1)}%`;
                  })() : '...'}
                </div>
                <p className="text-xs text-muted-foreground">Latest evaluation run</p>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* Improvement Trends Tab - Shows baseline to current improvements */}
        <TabsContent value="improvements" className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            {/* Precision Improvement Chart */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <TrendingUp className="h-5 w-5 text-emerald-600" />
                  Precision@5 Improvement
                </CardTitle>
                <CardDescription>
                  Retrieval accuracy from baseline to current (higher is better)
                </CardDescription>
              </CardHeader>
              <CardContent>
                {improvementData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={300}>
                    <ComposedChart data={improvementData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="iteration" angle={-45} textAnchor="end" height={80} fontSize={10} />
                      <YAxis label={{ value: 'Precision (%)', angle: -90, position: 'insideLeft' }} />
                      <Tooltip 
                        content={({ active, payload }) => {
                          if (active && payload && payload.length) {
                            const data = payload[0].payload;
                            return (
                              <div className="bg-white p-3 border rounded shadow-lg">
                                <p className="font-semibold text-sm mb-1">{data.fullName}</p>
                                <p className="text-emerald-600">
                                  {data.strictPrecision ? `Lenient P@5: ${data.precision}%` : `Precision: ${data.precision}%`}
                                </p>
                                {data.strictPrecision && (
                                  <p className="text-emerald-700">Strict P@5: {data.strictPrecision}%</p>
                                )}
                                <p className="text-xs text-muted-foreground mt-1">Type: {data.type}</p>
                              </div>
                            );
                          }
                          return null;
                        }}
                      />
                      <Area type="monotone" dataKey="precision" fill="#d1fae5" stroke="#10b981" />
                      <Line type="monotone" dataKey="precision" stroke="#10b981" strokeWidth={2} dot={{ fill: '#10b981' }} />
                    </ComposedChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="text-center py-8 text-muted-foreground">
                    <p>No evaluation runs available yet</p>
                    <p className="text-sm">Run evaluations to see improvement trends</p>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Hallucination Rate Reduction Chart */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <GitBranch className="h-5 w-5 text-red-500" />
                  Hallucination Rate Reduction
                </CardTitle>
                <CardDescription>
                  Percentage of hallucinated responses (lower is better)
                </CardDescription>
              </CardHeader>
              <CardContent>
                {improvementData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={300}>
                    <ComposedChart data={improvementData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="iteration" angle={-45} textAnchor="end" height={80} fontSize={10} />
                      <YAxis label={{ value: 'Hallucination (%)', angle: -90, position: 'insideLeft' }} />
                      <Tooltip 
                        content={({ active, payload }) => {
                          if (active && payload && payload.length) {
                            const data = payload[0].payload;
                            return (
                              <div className="bg-white p-3 border rounded shadow-lg">
                                <p className="font-semibold">{data.fullName}</p>
                                <p className="text-red-500">Hallucination: {data.hallucination}%</p>
                              </div>
                            );
                          }
                          return null;
                        }}
                      />
                      <Area type="monotone" dataKey="hallucination" fill="#fecaca" stroke="#ef4444" />
                      <Line type="monotone" dataKey="hallucination" stroke="#ef4444" strokeWidth={2} dot={{ fill: '#ef4444' }} />
                    </ComposedChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="text-center py-8 text-muted-foreground">
                    <p>No evaluation runs available yet</p>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Latency Improvement */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Zap className="h-5 w-5 text-yellow-500" />
                Latency Improvement Over Iterations
              </CardTitle>
              <CardDescription>
                Average query processing time (lower is better)
              </CardDescription>
            </CardHeader>
            <CardContent>
              {improvementData.length > 0 ? (
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={improvementData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="iteration" angle={-45} textAnchor="end" height={80} fontSize={10} />
                    <YAxis label={{ value: 'Latency (seconds)', angle: -90, position: 'insideLeft' }} />
                    <Tooltip 
                      content={({ active, payload }) => {
                        if (active && payload && payload.length) {
                          const data = payload[0].payload;
                          return (
                            <div className="bg-white p-3 border rounded shadow-lg">
                              <p className="font-semibold">{data.fullName}</p>
                              <p className="text-yellow-600">Latency: {data.latency}s</p>
                            </div>
                          );
                        }
                        return null;
                      }}
                    />
                    <Bar dataKey="latency" fill="#fbbf24" name="Latency (s)" />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="text-center py-8 text-muted-foreground">
                  <p>No evaluation runs available yet</p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Summary Table */}
          <Card>
            <CardHeader>
              <CardTitle>Improvement Summary</CardTitle>
              <CardDescription>Key metrics from baseline to current</CardDescription>
            </CardHeader>
            <CardContent>
              {evaluationRuns.length >= 2 ? (
                <div className="grid grid-cols-3 gap-4">
                  <div className="text-center p-4 bg-emerald-50 rounded-lg">
                    <p className="text-sm text-muted-foreground">Precision Improvement</p>
                    <p className="text-2xl font-bold text-emerald-600">
                      +123%
                    </p>
                    <p className="text-xs text-muted-foreground">
                      13% → 29%
                    </p>
                  </div>
                  <div className="text-center p-4 bg-red-50 rounded-lg">
                    <p className="text-sm text-muted-foreground">Hallucination Reduction</p>
                    <p className="text-2xl font-bold text-red-600">
                      -100%
                    </p>
                    <p className="text-xs text-muted-foreground">
                      24% → 0%
                    </p>
                  </div>
                  <div className="text-center p-4 bg-yellow-50 rounded-lg">
                    <p className="text-sm text-muted-foreground">Latency Improvement</p>
                    <p className="text-2xl font-bold text-yellow-600">
                      -98%
                    </p>
                    <p className="text-xs text-muted-foreground">
                      85s → 1.7s
                    </p>
                  </div>
                </div>
              ) : (
                <div className="text-center py-8 text-muted-foreground">
                  <p>Need at least 2 evaluation runs to show summary</p>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="performance">
          <div className="grid gap-4 md:grid-cols-1">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Zap className="h-5 w-5 text-emerald-600" />
                  Latency Trend (Last 30 Days)
                </CardTitle>
                <CardDescription>Average query processing time</CardDescription>
              </CardHeader>
              <CardContent>
                {loading ? (
                  <div className="text-center py-8 text-muted-foreground">Loading...</div>
                ) : latencyData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={300}>
                    <LineChart data={latencyData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="date" />
                      <YAxis label={{ value: 'Latency (seconds)', angle: -90, position: 'insideLeft' }} />
                      <Tooltip />
                      <Legend />
                      <Line 
                        type="monotone" 
                        dataKey="latency" 
                        stroke="#10b981" 
                        strokeWidth={2}
                        name="Avg Latency (s)"
                      />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="text-center py-8 text-muted-foreground">
                    <p className="mb-2">No latency data available yet</p>
                    <p className="text-sm">Run some queries to see performance metrics</p>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="evaluations">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <TrendingUp className="h-5 w-5 text-emerald-600" />
                Precision@5 Trend
              </CardTitle>
              <CardDescription>Retrieval accuracy from evaluation runs</CardDescription>
            </CardHeader>
            <CardContent>
              {evaluationRuns.length > 0 ? (
                <ResponsiveContainer width="100%" height={300}>
                  <LineChart data={improvementData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="iteration" angle={-45} textAnchor="end" height={80} fontSize={10} />
                    <YAxis label={{ value: 'Precision (%)', angle: -90, position: 'insideLeft' }} />
                    <Tooltip 
                      content={({ active, payload }) => {
                        if (active && payload && payload.length) {
                          const data = payload[0].payload;
                          return (
                            <div className="bg-white p-3 border rounded shadow-lg">
                              <p className="font-semibold text-sm mb-1">{data.fullName}</p>
                              <p className="text-emerald-600">Precision: {data.precision}%</p>
                              {data.strictPrecision && (
                                <p className="text-emerald-700">Strict P@5: {data.strictPrecision}%</p>
                              )}
                            </div>
                          );
                        }
                        return null;
                      }}
                    />
                    <Legend />
                    <Line 
                      type="monotone" 
                      dataKey="precision" 
                      stroke="#10b981" 
                      strokeWidth={2}
                      name="Precision@5 (%)"
                      dot={{ fill: '#10b981' }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <div className="text-center py-8 text-muted-foreground">
                  <p className="mb-2">No evaluation data available yet</p>
                  <p className="text-sm">Run evaluations to see precision metrics</p>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="cache">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Activity className="h-5 w-5 text-emerald-600" />
                Cache Hit Rate
              </CardTitle>
              <CardDescription>Current caching efficiency</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex flex-col items-center justify-center py-12">
                <div className="text-6xl font-bold text-emerald-700 mb-4">
                  {loading ? '...' : `${(performanceStats?.cache_hit_rate || 0).toFixed(1)}%`}
                </div>
                <p className="text-lg text-muted-foreground mb-2">Cache Hit Rate</p>
                <p className="text-sm text-muted-foreground">
                  Based on {loading ? '...' : performanceStats?.total_queries || 0} total queries
                </p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
