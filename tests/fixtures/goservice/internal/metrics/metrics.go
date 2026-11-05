package metrics

// Counter is a trivial in-process counter used for request metrics.
type Counter struct{ n int }

func (c *Counter) Inc() { c.n++ }
