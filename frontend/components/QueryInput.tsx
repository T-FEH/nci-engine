'use client';

import { useState } from 'react';
import { Loader2, Send, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { apiClient } from '@/lib/api';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

const EXAMPLE_QUERIES = [
  "I need a tool to manage my team's projects and track tasks",
  "Looking for AI to help write marketing emails for my e-commerce store",
  "Want to automate social media posting across multiple platforms",
  "Need to transcribe podcast episodes and create blog posts from them",
];

export default function QueryInput() {
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) {
      toast.error('Please enter a query');
      return;
    }

    setLoading(true);
    toast.loading('Analyzing your query...', { id: 'analysis' });

    try {
      const result = await apiClient.submitQuery(query, true);
      
      if (result.success && result.data) {
        toast.success('Analysis complete!', { id: 'analysis' });
        // Store result in sessionStorage for the results page
        sessionStorage.setItem('latest_analysis', JSON.stringify(result.data));
        router.push('/results');
      } else {
        toast.error(result.error || 'Failed to analyze query', { id: 'analysis' });
      }
    } catch (err: any) {
      toast.error(err.message || 'An unexpected error occurred', { id: 'analysis' });
    } finally {
      setLoading(false);
    }
  };

  const handleExampleClick = (exampleQuery: string) => {
    setQuery(exampleQuery);
    toast.success('Example loaded');
  };

  return (
    <div className="container max-w-4xl mx-auto px-4 py-12">
      <div className="text-center mb-12">
        <div className="flex items-center justify-center gap-2 mb-4">
          <Sparkles className="h-8 w-8 text-emerald-600" />
          <h1 className="text-4xl font-bold">
            No-Code Intelligence Engine
          </h1>
        </div>
        <p className="text-xl text-muted-foreground">
          Discover the perfect AI tools for your needs
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Describe Your Need</CardTitle>
          <CardDescription>
            Tell us what you're trying to achieve, and we'll recommend the best tools for your workflow
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <Textarea
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Example: I need a tool to help me create engaging social media content for my small business..."
              className="min-h-[120px] resize-none focus-visible:ring-emerald-500"
              disabled={loading}
            />

            <Button 
              type="submit" 
              size="lg" 
              className="w-full bg-emerald-600 hover:bg-emerald-700"
              disabled={loading || !query.trim()}
            >
              {loading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Analyzing...
                </>
              ) : (
                <>
                  <Send className="mr-2 h-4 w-4" />
                  Find Solutions
                </>
              )}
            </Button>
          </form>

          <div className="mt-8">
            <p className="text-sm text-muted-foreground mb-3">Try these examples:</p>
            <div className="grid gap-2">
              {EXAMPLE_QUERIES.map((example, index) => (
                <button
                  key={index}
                  onClick={() => handleExampleClick(example)}
                  className="text-left p-3 rounded-lg border border-border hover:bg-accent hover:border-emerald-300 transition-colors text-sm"
                  disabled={loading}
                >
                  {example}
                </button>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
