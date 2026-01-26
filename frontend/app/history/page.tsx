'use client';

import { useEffect, useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { History, Search, ChevronLeft, ChevronRight } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { toast } from 'sonner';

interface HistoryItem {
  id: number;
  query: string;
  user_id: string | null;
  validation_score: number;
  has_hallucination: boolean;
  duration_ms: number;
  created_at: string;
}

interface HistoryResponse {
  items: HistoryItem[];
  total: number;
  limit: number;
  offset: number;
}

export default function HistoryPage() {
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const limit = 20;

  useEffect(() => {
    fetchHistory();
  }, [page]);

  const fetchHistory = async () => {
    try {
      setLoading(true);
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
      const response = await fetch(
        `${apiUrl}/api/v1/analyze/history?limit=${limit}&offset=${page * limit}`
      );

      if (!response.ok) {
        const errorText = await response.text();
        console.error(`History API error ${response.status}:`, errorText);
        throw new Error(`Failed to fetch history: ${response.status}`);
      }

      const data: HistoryResponse = await response.json();
      setHistory(data.items);
      setTotal(data.total);
    } catch (error) {
      console.error('Error fetching history:', error);
      toast.error('Failed to load history');
    } finally {
      setLoading(false);
    }
  };

  const filteredHistory = history.filter((item) =>
    item.query.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleString();
  };

  const formatDuration = (ms: number) => {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  const getScoreBadge = (score: number) => {
    if (score >= 0.8) return <Badge className="bg-emerald-600">High</Badge>;
    if (score >= 0.5) return <Badge className="bg-yellow-600">Medium</Badge>;
    return <Badge className="bg-red-600">Low</Badge>;
  };

  const totalPages = Math.ceil(total / limit);

  return (
    <div className="container max-w-7xl mx-auto px-4 py-12">
      <div className="mb-8">
        <h1 className="text-3xl font-bold mb-2">Analysis History</h1>
        <p className="text-muted-foreground">View your past queries and results</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <History className="h-5 w-5 text-emerald-600" />
            Query History
          </CardTitle>
          <CardDescription>
            {total} total queries analyzed
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="mb-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search queries..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-10"
              />
            </div>
          </div>

          {loading ? (
            <div className="text-center py-8 text-muted-foreground">Loading...</div>
          ) : filteredHistory.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              {searchQuery ? 'No matching queries found' : 'No history yet'}
            </div>
          ) : (
            <>
              <div className="rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Query</TableHead>
                      <TableHead>Validation</TableHead>
                      <TableHead>Hallucination</TableHead>
                      <TableHead>Duration</TableHead>
                      <TableHead>Date</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredHistory.map((item) => (
                      <TableRow 
                        key={item.id} 
                        className="cursor-pointer hover:bg-emerald-50 transition-colors"
                        onClick={() => {
                          // Store analysis ID and navigate to results
                          sessionStorage.setItem('currentAnalysisId', item.id.toString());
                          window.location.href = `/results?id=${item.id}`;
                        }}
                      >
                        <TableCell className="max-w-md">
                          <div className="truncate font-medium">{item.query}</div>
                        </TableCell>
                        <TableCell>{getScoreBadge(item.validation_score)}</TableCell>
                        <TableCell>
                          {item.has_hallucination ? (
                            <Badge variant="destructive">Yes</Badge>
                          ) : (
                            <Badge className="bg-emerald-600">No</Badge>
                          )}
                        </TableCell>
                        <TableCell className="text-emerald-700 font-medium">
                          {formatDuration(item.duration_ms)}
                        </TableCell>
                        <TableCell className="text-muted-foreground text-sm">
                          {formatDate(item.created_at)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              {!searchQuery && totalPages > 1 && (
                <div className="flex items-center justify-between mt-4">
                  <div className="text-sm text-muted-foreground">
                    Page {page + 1} of {totalPages}
                  </div>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setPage(page - 1)}
                      disabled={page === 0}
                      className="border-emerald-600 text-emerald-600 hover:bg-emerald-50"
                    >
                      <ChevronLeft className="h-4 w-4 mr-1" />
                      Previous
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setPage(page + 1)}
                      disabled={page >= totalPages - 1}
                      className="border-emerald-600 text-emerald-600 hover:bg-emerald-50"
                    >
                      Next
                      <ChevronRight className="h-4 w-4 ml-1" />
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
