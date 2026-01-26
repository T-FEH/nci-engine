'use client';

import { useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { ArrowLeft, Clock, CheckCircle2, AlertCircle, ExternalLink, ThumbsUp, ThumbsDown, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { toast } from 'sonner';
import type { AnalysisResult } from '@/lib/types';
import { formatDuration } from '@/lib/utils';

export default function ResultsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [feedback, setFeedback] = useState<'up' | 'down' | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchAnalysis = async () => {
      setLoading(true);
      
      // Check if there's an ID in the URL (from history page)
      const analysisId = searchParams.get('id');
      
      if (analysisId) {
        // Fetch specific analysis from API
        try {
          const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
          const response = await fetch(`${apiUrl}/api/v1/analyze/${analysisId}`);
          
          if (response.ok) {
            const data = await response.json();
            setResult(data);
            sessionStorage.setItem('currentAnalysisId', analysisId);
          } else {
            toast.error('Failed to load analysis');
            router.push('/');
          }
        } catch (error) {
          console.error('Error fetching analysis:', error);
          toast.error('Failed to load analysis');
          router.push('/');
        }
      } else {
        // Check session storage for latest analysis
        const stored = sessionStorage.getItem('latest_analysis');
        if (stored) {
          setResult(JSON.parse(stored));
        } else {
          router.push('/');
        }
      }
      
      setLoading(false);
    };

    fetchAnalysis();
  }, [router, searchParams]);

  const handleFeedback = async (type: 'up' | 'down') => {
    setFeedback(type);
    
    const analysisId = sessionStorage.getItem('currentAnalysisId');
    if (!analysisId && result) {
      // If no stored ID, try to get from result
      console.warn('No analysis ID found in session storage');
    }
    
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
      const response = await fetch(`${apiUrl}/api/v1/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          analysis_id: analysisId ? parseInt(analysisId) : null,
          feedback_type: type,
          comment: null
        })
      });
      
      if (response.ok) {
        toast.success('Thank you for your feedback!');
      } else {
        toast.error('Failed to save feedback');
      }
    } catch (error) {
      console.error('Failed to submit feedback:', error);
      toast.success('Thank you for your feedback!'); // Still show success to user
    }
  };

  if (loading) {
    return (
      <div className="container max-w-6xl mx-auto px-4 py-12">
        <div className="flex items-center justify-center gap-2">
          <Loader2 className="h-6 w-6 animate-spin text-emerald-600" />
          <span>Loading analysis...</span>
        </div>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="container max-w-6xl mx-auto px-4 py-12">
        <div className="text-center">Loading...</div>
      </div>
    );
  }

  return (
    <div className="container max-w-6xl mx-auto px-4 py-8">
      <Button
        variant="ghost"
        onClick={() => router.push('/')}
        className="mb-6"
      >
        <ArrowLeft className="mr-2 h-4 w-4" />
        New Query
      </Button>

      {/* Header with validation */}
      <div className="mb-8">
        <div className="flex items-start justify-between mb-4">
          <div className="flex-1">
            <h1 className="text-3xl font-bold mb-2">Analysis Complete</h1>
            {result.duration_ms && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Clock className="h-4 w-4" />
                Completed in {formatDuration(result.duration_ms)}
              </div>
            )}
          </div>
          <div className="flex items-center gap-3">
            <div className="flex gap-2">
              <Button
                variant={feedback === 'up' ? 'default' : 'outline'}
                size="sm"
                onClick={() => handleFeedback('up')}
                className={feedback === 'up' ? 'bg-emerald-600 hover:bg-emerald-700' : ''}
              >
                <ThumbsUp className="h-4 w-4 mr-1" />
                Helpful
              </Button>
              <Button
                variant={feedback === 'down' ? 'destructive' : 'outline'}
                size="sm"
                onClick={() => handleFeedback('down')}
              >
                <ThumbsDown className="h-4 w-4 mr-1" />
                Not Helpful
              </Button>
            </div>
            <Separator orientation="vertical" className="h-8" />
            <div className="flex items-center gap-2">{result.validation.is_valid ? (
              <Badge variant="default" className="gap-1 bg-emerald-600">
                <CheckCircle2 className="h-3 w-3" />
                Validated
              </Badge>
            ) : (
              <Badge variant="destructive" className="gap-1">
                <AlertCircle className="h-3 w-3" />
                Needs Review
              </Badge>
            )}
            <Badge variant="outline">
              Score: {result.validation.score.toFixed(1)}/5
            </Badge>
          </div>
          </div>
        </div>
        {result.validation.has_hallucination && (
          <div className="p-3 bg-destructive/10 text-destructive rounded-md text-sm">
            <AlertCircle className="h-4 w-4 inline mr-2" />
            Warning: Potential hallucination detected in recommendations
          </div>
        )}
      </div>

      <Tabs defaultValue="problem" className="space-y-6">
        <TabsList className="grid w-full grid-cols-4">
          <TabsTrigger value="problem">Problem Analysis</TabsTrigger>
          <TabsTrigger value="tools">Recommended Tools</TabsTrigger>
          <TabsTrigger value="roadmap">Implementation Roadmap</TabsTrigger>
          <TabsTrigger value="validation">Quality Metrics</TabsTrigger>
        </TabsList>

        <TabsContent value="problem" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Identified Bottleneck</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <h3 className="font-semibold mb-2">Problem Statement</h3>
                <p className="text-muted-foreground">{result.bottleneck.problem}</p>
              </div>
              <Separator />
              <div>
                <h3 className="font-semibold mb-2">Primary Goal</h3>
                <p className="text-muted-foreground">{result.bottleneck.goal}</p>
              </div>
              <Separator />
              <div>
                <h3 className="font-semibold mb-2">Use Case</h3>
                <Badge variant="secondary">{result.bottleneck.use_case}</Badge>
              </div>
              {result.bottleneck.constraints.length > 0 && (
                <>
                  <Separator />
                  <div>
                    <h3 className="font-semibold mb-2">Constraints</h3>
                    <ul className="list-disc list-inside space-y-1 text-muted-foreground">
                      {result.bottleneck.constraints.map((constraint, idx) => (
                        <li key={idx}>{constraint}</li>
                      ))}
                    </ul>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="tools" className="space-y-4">
          {result.tools.length === 0 && (
            <Card>
              <CardContent className="py-8 text-center text-muted-foreground">
                No tools recommended for this query.
              </CardContent>
            </Card>
          )}
          <div className="grid gap-4">
            {result.tools.map((tool, idx) => (
              <Card key={idx} className="overflow-hidden">
                <CardHeader>
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <CardTitle className="flex items-center gap-2 flex-wrap">
                        <span className="break-words">{tool.name}</span>
                        {idx === 0 && (
                          <Badge variant="default" className="shrink-0 bg-emerald-600">Primary</Badge>
                        )}
                        {idx > 0 && (
                          <Badge variant="secondary" className="shrink-0">Supporting</Badge>
                        )}
                      </CardTitle>
                      <CardDescription className="mt-2 break-words whitespace-pre-wrap">{tool.summary}</CardDescription>
                    </div>
                    {tool.url && (
                      <Button variant="outline" size="sm" asChild className="shrink-0">
                        <a href={tool.url} target="_blank" rel="noopener noreferrer">
                          <ExternalLink className="h-4 w-4 mr-2" />
                          Visit
                        </a>
                      </Button>
                    )}
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  {tool.stack_purpose && (
                    <div>
                      <h4 className="text-sm font-semibold mb-1">Role in Solution</h4>
                      <p className="text-sm text-muted-foreground break-words whitespace-pre-wrap">{tool.stack_purpose}</p>
                    </div>
                  )}
                  
                  <div className="grid md:grid-cols-2 gap-4">
                    {tool.pricing_model && (
                      <div>
                        <h4 className="text-sm font-semibold mb-2">Pricing</h4>
                        <Badge variant="outline" className="break-words whitespace-normal max-w-full inline-block">{tool.pricing_model}</Badge>
                      </div>
                    )}
                    {tool.features && tool.features.length > 0 && (
                      <div>
                        <h4 className="text-sm font-semibold mb-2">Key Features</h4>
                        <div className="flex flex-wrap gap-1">
                          {tool.features.slice(0, 5).map((feature, fi) => (
                            <Badge key={fi} variant="secondary" className="text-xs break-words whitespace-normal">
                              {feature}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>

        <TabsContent value="roadmap" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Implementation Overview</CardTitle>
              <CardDescription>{result.roadmap.overview}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="flex items-center gap-4 text-sm">
                <div>
                  <span className="text-muted-foreground">Total Duration:</span>
                  <span className="ml-2 font-semibold">{result.roadmap.total_duration}</span>
                </div>
              </div>

              <Separator />

              {result.action_plans.map((plan, idx) => (
                <div key={idx} className="space-y-3">
                  <div className="flex items-start gap-3">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
                      {plan.rank}
                    </div>
                    <div className="space-y-1 flex-1">
                      <h3 className="font-semibold">{plan.title}</h3>
                      <p className="text-sm text-muted-foreground">{plan.description}</p>
                      <div className="flex items-center gap-2">
                        <Clock className="h-3 w-3 text-muted-foreground" />
                        <span className="text-xs text-muted-foreground">{plan.duration}</span>
                      </div>
                    </div>
                  </div>
                  {plan.tasks.length > 0 && (
                    <ul className="ml-11 space-y-1 text-sm">
                      {plan.tasks.map((task, ti) => (
                        <li key={ti} className="flex items-start gap-2">
                          <span className="text-muted-foreground">•</span>
                          <span className="text-muted-foreground">{task}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                  {idx < result.action_plans.length - 1 && <Separator className="mt-6" />}
                </div>
              ))}

              {result.roadmap.success_metrics.length > 0 && (
                <>
                  <Separator />
                  <div>
                    <h3 className="font-semibold mb-3">Success Metrics</h3>
                    <ul className="space-y-2">
                      {result.roadmap.success_metrics.map((metric, idx) => (
                        <li key={idx} className="flex items-start gap-2 text-sm">
                          <CheckCircle2 className="h-4 w-4 text-emerald-600 mt-0.5 shrink-0" />
                          <span className="break-words">{metric}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="validation" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Quality Assessment</CardTitle>
              <CardDescription>LLM-based validation of the recommendations</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <div className="flex justify-between">
                    <span className="text-sm font-medium">Overall Score</span>
                    <span className="text-sm font-bold">{result.validation.score.toFixed(1)}/5.0</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-sm font-medium">Verdict</span>
                    <Badge variant={result.validation.is_valid ? "default" : "destructive"}>
                      {result.validation.verdict || "Not Evaluated"}
                    </Badge>
                  </div>
                </div>
                <div className="space-y-2">
                  <div className="flex justify-between">
                    <span className="text-sm font-medium">Hallucination Check</span>
                    <Badge variant={result.validation.has_hallucination ? "destructive" : "default"}>
                      {result.validation.has_hallucination ? "Detected" : "None"}
                    </Badge>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-sm font-medium">Real Tools</span>
                    <Badge variant={result.validation.recommends_real_tools ? "default" : "destructive"}>
                      {result.validation.recommends_real_tools ? "Yes" : "No"}
                    </Badge>
                  </div>
                </div>
              </div>

              {result.validation.reasoning && (
                <>
                  <Separator />
                  <div className="space-y-3">
                    <h3 className="font-semibold">Detailed Reasoning</h3>
                    {result.validation.reasoning.relevance && (
                      <div>
                        <h4 className="text-sm font-medium mb-1">Relevance</h4>
                        <p className="text-sm text-muted-foreground">{result.validation.reasoning.relevance}</p>
                      </div>
                    )}
                    {result.validation.reasoning.helpfulness && (
                      <div>
                        <h4 className="text-sm font-medium mb-1">Helpfulness</h4>
                        <p className="text-sm text-muted-foreground">{result.validation.reasoning.helpfulness}</p>
                      </div>
                    )}
                    {result.validation.reasoning.factuality && (
                      <div>
                        <h4 className="text-sm font-medium mb-1">Factuality</h4>
                        <p className="text-sm text-muted-foreground">{result.validation.reasoning.factuality}</p>
                      </div>
                    )}
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
